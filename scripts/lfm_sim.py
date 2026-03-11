"""
lfm_sim.py — Light Field Microscope Simulation Module

Educational tool for understanding LFM optics. Uses pyolaf's wave-optics
forward model (Huygens-Fresnel diffraction + Rayleigh-Sommerfeld propagation)
to generate synthetic light field images and reconstruct 3D volumes.

No ray tracing software needed — the wave-optics model is more accurate than
geometric ray tracing at microlens scales where diffraction matters.

Usage:
    from lfm_sim import LFMSimConfig, setup_simulation, forward_project, reconstruct

    config = LFMSimConfig()              # default optics
    sim = setup_simulation(config)       # build forward model (~30s for 'fast')
    volume = create_point_sources(sim['volumeSize'], [(0.5, 0.5, 0.5)])
    lf_image = forward_project(volume, sim)
    recon = reconstruct(lf_image, sim)
"""

import os
import sys
import copy
import tempfile
from dataclasses import dataclass, field, asdict
from time import time
from typing import Optional

import numpy as np
import matplotlib.pyplot as plt
import yaml

# Add project root to path for pyolaf imports
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from pyolaf.geometry import LFM_setCameraParams, LFM_computeGeometryParameters
from pyolaf.lf import LFM_computeLFMatrixOperators
from pyolaf.aliasing import LFM_computeDepthAdaptiveWidth, lanczosfft
from pyolaf.project import LFM_forwardProject, LFM_backwardProject

try:
    import cupy
    from cupy.fft import fftshift, ifft2, fft2
    _has_cupy = True
except ImportError:
    cupy = np
    from numpy.fft import fftshift, ifft2, fft2
    _has_cupy = False


# ---------------------------------------------------------------------------
# Quality presets
# ---------------------------------------------------------------------------

QUALITY_PRESETS = {
    'fast':   dict(img_size=(301, 301), new_spacing_px=19, super_res_factor=3,
                   n_iterations=1, lanczos_window=3),
    'medium': dict(img_size=(501, 501), new_spacing_px=15, super_res_factor=5,
                   n_iterations=2, lanczos_window=4),
    'high':   dict(img_size=(751, 751), new_spacing_px=13, super_res_factor=7,
                   n_iterations=3, lanczos_window=4),
}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class LFMSimConfig:
    """Configuration for LFM simulation.

    Wraps pyolaf's YAML config format in a Python dataclass for easy
    parameter exploration. All physical units in micrometers unless noted.

    Attributes:
        M: Objective magnification
        NA: Objective numerical aperture
        ftl: Tube lens focal length (um)
        fm: Microlens focal length (um)
        lens_pitch: Microlens pitch (um)
        pixel_pitch: Sensor pixel pitch (um)
        wavelength: Emission wavelength (um)
        n: Refractive index of medium
        plenoptic: Plenoptic type (1 = standard LFM, 2 = defocused)
        grid_type: 'reg' (regular) or 'hex' (hexagonal)
        u_lens_mask: 1 = rectangular aperture, 0 = circular
        depth_range: (min, max) depth range in um
        depth_step: Depth step in um
        quality: 'fast', 'medium', or 'high' — sets resolution presets
        n_iterations: Override deconvolution iterations (None = use quality preset)
        filter_flag: Enable anti-aliasing filter during reconstruction
    """
    # Objective
    M: float = 10.0
    NA: float = 0.3
    ftl: float = 200_000.0
    # Microlens array
    fm: float = 1875.0
    lens_pitch: float = 125.0
    # Sensor
    pixel_pitch: float = 6.5
    # Light
    wavelength: float = 0.525
    n: float = 1.0
    # Geometry
    plenoptic: int = 1
    grid_type: str = 'reg'
    u_lens_mask: int = 1
    # Depth
    depth_range: tuple = (-300, 300)
    depth_step: float = 150.0
    # Quality
    quality: str = 'fast'
    n_iterations: Optional[int] = None
    filter_flag: bool = True

    def to_yaml_dict(self):
        """Convert to pyolaf-compatible YAML dictionary."""
        return {
            'gridType': self.grid_type,
            'focus': 'single',
            'plenoptic': self.plenoptic,
            'uLensMask': self.u_lens_mask,
            'M': self.M,
            'NA': self.NA,
            'ftl': self.ftl,
            'fm': self.fm,
            'lensPitch': self.lens_pitch,
            'pixelPitch': self.pixel_pitch,
            'WaveLength': self.wavelength,
            'n': self.n,
            'tube2mla': self.ftl if self.plenoptic == 1 else 0,
            'mla2sensor': 0,
        }

    def get_preset(self):
        """Get the quality preset parameters."""
        return QUALITY_PRESETS[self.quality]

    def summary(self):
        """Print a human-readable summary of the configuration."""
        fobj = self.ftl / self.M
        px_per_lens = self.lens_pitch / self.pixel_pitch
        print(f"=== LFM Configuration ===")
        print(f"  Objective: {self.M}x / NA {self.NA}")
        print(f"  f_obj = {fobj:.0f} um, f_tube = {self.ftl:.0f} um")
        print(f"  Microlens: pitch={self.lens_pitch} um, f={self.fm} um")
        print(f"  Sensor pixel: {self.pixel_pitch} um ({px_per_lens:.1f} px/lenslet)")
        print(f"  Wavelength: {self.wavelength} um, n={self.n}")
        print(f"  Depth range: [{self.depth_range[0]}, {self.depth_range[1]}] um, "
              f"step={self.depth_step} um")
        print(f"  Quality: '{self.quality}'")


# ---------------------------------------------------------------------------
# Core simulation pipeline
# ---------------------------------------------------------------------------

def setup_simulation(config: LFMSimConfig, img_size=None, verbose=True):
    """Initialize the pyolaf forward model from configuration.

    Uses pyolaf's simulation-mode path (empty WhiteImage) to build an ideal
    lenslet grid from specs — no physical calibration image needed.

    Args:
        config: LFMSimConfig with optical parameters.
        img_size: (ny, nx) sensor image size in pixels. If None, uses quality preset.
        verbose: Print progress and timing info.

    Returns:
        dict with keys: Camera, Resolution, LensletCenters, H, Ht,
        imgSize, texSize, volumeSize, kernelFFT, config, crange.
    """
    preset = config.get_preset()
    if img_size is None:
        img_size = preset['img_size']
    new_spacing_px = preset['new_spacing_px']
    super_res_factor = preset['super_res_factor']
    lanczos_window = preset['lanczos_window']

    t0 = time()

    # 1. Write temp YAML config
    yaml_dict = config.to_yaml_dict()
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
    yaml.dump(yaml_dict, tmp)
    tmp.close()

    try:
        # 2. Load camera params
        if verbose:
            print("Setting up camera parameters...")
        Camera = LFM_setCameraParams(tmp.name, new_spacing_px)
    finally:
        os.unlink(tmp.name)

    # 3. Compute geometry (simulation mode: empty WhiteImage)
    if verbose:
        print("Computing geometry (simulation mode)...")
    depth_range = list(config.depth_range)
    LensletCenters, Resolution, LensletGridModel, NewLensletGridModel = \
        LFM_computeGeometryParameters(
            Camera, np.array([]), depth_range, config.depth_step,
            super_res_factor, imgSize=np.array(img_size))

    t1 = time()
    if verbose:
        print(f"  Geometry ready in {t1 - t0:.1f}s")

    # 4. Compute wave-optics PSF operators (the expensive step)
    if verbose:
        print("Computing PSF operators (this may take a while)...")
    H, Ht = LFM_computeLFMatrixOperators(Camera, Resolution, LensletCenters)

    t2 = time()
    if verbose:
        print(f"  PSF operators ready in {t2 - t1:.1f}s")

    # 5. Compute image/volume sizes
    imgSize = np.array(img_size)
    imgSize = imgSize + (1 - np.remainder(imgSize, 2))  # ensure odd

    texSize = np.ceil(np.multiply(imgSize, Resolution['texScaleFactor'])).astype('int32')
    texSize = texSize + (1 - np.remainder(texSize, 2))  # ensure odd

    ndepths = len(Resolution['depths'])
    volumeSize = np.append(texSize, ndepths).astype('int32')

    # 6. Build anti-aliasing filter kernels
    widths = LFM_computeDepthAdaptiveWidth(Camera, Resolution)
    kernelFFT = lanczosfft(volumeSize, widths, lanczos_window)

    n_iter = config.n_iterations if config.n_iterations is not None else preset['n_iterations']

    t3 = time()
    if verbose:
        print(f"  Total setup time: {t3 - t0:.1f}s")
        print(f"  Volume shape: {tuple(volumeSize)} (ny, nx, n_depths)")
        print(f"  Image shape: {tuple(imgSize)}")
        depths = Resolution['depths']
        print(f"  Depth planes: {ndepths} from {depths[0]:.0f} to {depths[-1]:.0f} um")

    return {
        'Camera': Camera,
        'Resolution': Resolution,
        'LensletCenters': LensletCenters,
        'H': H,
        'Ht': Ht,
        'imgSize': imgSize,
        'texSize': texSize,
        'volumeSize': volumeSize,
        'kernelFFT': kernelFFT,
        'config': config,
        'crange': Camera['range'],
        'n_iterations': n_iter,
    }


def forward_project(volume, sim_setup, noise_photons=None, lenslet_centers=None):
    """Generate a synthetic light field image from a 3D volume.

    Args:
        volume: 3D numpy array (ny, nx, n_depths) representing fluorescence intensity.
        sim_setup: dict from setup_simulation().
        noise_photons: If set, add Poisson noise scaled to this photon count.
            Higher = less noisy. None = no noise (clean simulation).
        lenslet_centers: Optional modified LensletCenters dict for misalignment
            simulation. If None, uses the ideal centers from sim_setup.

    Returns:
        2D numpy array — the simulated light field image on the sensor.
    """
    H = sim_setup['H']
    Resolution = sim_setup['Resolution']
    imgSize = sim_setup['imgSize']
    crange = sim_setup['crange']
    centers = lenslet_centers if lenslet_centers is not None else sim_setup['LensletCenters']

    lf_image = LFM_forwardProject(H, volume, centers, Resolution, imgSize, crange, step=8)

    # Convert from cupy if needed
    if _has_cupy and hasattr(lf_image, 'get'):
        lf_image = lf_image.get()
    lf_image = np.asarray(lf_image, dtype='float32')

    # Ensure non-negative
    lf_image = np.maximum(lf_image, 0)

    # Add Poisson noise if requested
    if noise_photons is not None and noise_photons > 0:
        # Scale to photon counts, apply Poisson, scale back
        max_val = lf_image.max()
        if max_val > 0:
            scaled = lf_image / max_val * noise_photons
            noisy = np.random.poisson(scaled).astype('float32')
            lf_image = noisy / noise_photons * max_val

    return lf_image


def reconstruct(lf_image, sim_setup, n_iterations=None, lenslet_centers=None,
                verbose=True):
    """Reconstruct a 3D volume from a light field image via Richardson-Lucy deconvolution.

    Args:
        lf_image: 2D numpy array — light field image (from forward_project or real data).
        sim_setup: dict from setup_simulation().
        n_iterations: Override number of deconvolution iterations.
        lenslet_centers: Optional modified LensletCenters for reconstruction.
            Typically you use the *ideal* centers here, even if the forward
            projection used misaligned centers (to simulate what happens when
            you don't know about the misalignment).
        verbose: Print progress info.

    Returns:
        3D numpy array (ny, nx, n_depths) — reconstructed volume.
    """
    H = sim_setup['H']
    Ht = sim_setup['Ht']
    Resolution = sim_setup['Resolution']
    imgSize = sim_setup['imgSize']
    texSize = sim_setup['texSize']
    volumeSize = sim_setup['volumeSize']
    kernelFFT = sim_setup['kernelFFT']
    crange = sim_setup['crange']
    filter_flag = sim_setup['config'].filter_flag
    centers = lenslet_centers if lenslet_centers is not None else sim_setup['LensletCenters']

    niter = n_iterations if n_iterations is not None else sim_setup['n_iterations']

    # Normalize image to [0, 1]
    img = np.asarray(lf_image, dtype='float32')
    img_min, img_max = img.min(), img.max()
    if img_max > img_min:
        img = (img - img_min) / (img_max - img_min)

    LFimage = cupy.asarray(img)

    # Initialize volume
    initVolume = np.ones(volumeSize, dtype='float32')

    # Precompute normalization
    if verbose:
        print("Precomputing normalization projections...")
    onesForward = LFM_forwardProject(H, initVolume, centers, Resolution, imgSize, crange, step=8)
    onesBack = LFM_backwardProject(Ht, onesForward, centers, Resolution, texSize, crange, step=8)

    # Deconvolution loop
    reconVolume = cupy.asarray(np.copy(initVolume))
    t0 = time()

    for i in range(niter):
        if verbose:
            print(f"  Iteration {i + 1}/{niter}...")

        if i == 0:
            LFimageGuess = onesForward
        else:
            LFimageGuess = LFM_forwardProject(H, reconVolume, centers, Resolution,
                                               imgSize, crange, step=10)

        if _has_cupy:
            cupy.get_default_memory_pool().free_all_blocks()

        errorLFimage = LFimage / LFimageGuess * onesForward
        errorLFimage[~cupy.isfinite(errorLFimage)] = 0

        errorBack = LFM_backwardProject(Ht, errorLFimage, centers, Resolution,
                                         texSize, crange, step=10)
        if _has_cupy:
            cupy.get_default_memory_pool().free_all_blocks()

        errorBack = errorBack / onesBack
        errorBack[~cupy.isfinite(errorBack)] = 0

        reconVolume = reconVolume * errorBack

        if filter_flag:
            for j in range(reconVolume.shape[2]):
                reconVolume[:, :, j] = cupy.abs(
                    fftshift(ifft2(kernelFFT[:, :, j] * fft2(reconVolume[:, :, j]))))

        reconVolume[~cupy.isfinite(reconVolume)] = 0
        if _has_cupy:
            cupy.get_default_memory_pool().free_all_blocks()

    if _has_cupy and hasattr(reconVolume, 'get'):
        result = reconVolume.get()
    else:
        result = np.asarray(reconVolume)

    t1 = time()
    if verbose:
        print(f"  Reconstruction done in {t1 - t0:.1f}s ({niter} iterations)")

    return result


# ---------------------------------------------------------------------------
# Synthetic scene generators
# ---------------------------------------------------------------------------

def create_point_sources(volume_shape, positions, brightness=1.0):
    """Create a volume with point sources at specified positions.

    Args:
        volume_shape: (ny, nx, n_depths) shape of the volume.
        positions: List of (y_frac, x_frac, depth_frac) tuples, where each
            value is a fraction in [0, 1] of the volume extent.
            (0.5, 0.5, 0.5) = center of volume.
        brightness: Scalar or list of brightness values per point.

    Returns:
        3D numpy array with point sources.
    """
    volume = np.zeros(volume_shape, dtype='float32')
    ny, nx, nz = volume_shape

    if np.isscalar(brightness):
        brightness = [brightness] * len(positions)

    for (yf, xf, zf), b in zip(positions, brightness):
        iy = int(np.clip(yf * (ny - 1), 0, ny - 1))
        ix = int(np.clip(xf * (nx - 1), 0, nx - 1))
        iz = int(np.clip(zf * (nz - 1), 0, nz - 1))
        volume[iy, ix, iz] = b

    return volume


def create_fluorescent_beads(volume_shape, bead_positions, bead_radius_voxels=3,
                              brightness=1.0):
    """Create a volume with spherical fluorescent beads.

    Args:
        volume_shape: (ny, nx, n_depths) shape of the volume.
        bead_positions: List of (y_frac, x_frac, depth_frac) tuples in [0, 1].
        bead_radius_voxels: Radius of each bead in voxels (isotropic in y/x,
            scaled for depth axis based on volume aspect ratio).
        brightness: Scalar or list of brightness values.

    Returns:
        3D numpy array with fluorescent beads.
    """
    volume = np.zeros(volume_shape, dtype='float32')
    ny, nx, nz = volume_shape

    if np.isscalar(brightness):
        brightness = [brightness] * len(bead_positions)

    # Create coordinate grids
    yy, xx, zz = np.ogrid[0:ny, 0:nx, 0:nz]

    for (yf, xf, zf), b in zip(bead_positions, brightness):
        cy = yf * (ny - 1)
        cx = xf * (nx - 1)
        cz = zf * (nz - 1)

        # Compute distance (scale z by aspect ratio since depth is usually
        # much coarser than lateral dimensions)
        ry = bead_radius_voxels
        rx = bead_radius_voxels
        rz = max(1, bead_radius_voxels * nz / max(ny, nx))

        dist_sq = ((yy - cy) / ry) ** 2 + ((xx - cx) / rx) ** 2 + ((zz - cz) / rz) ** 2
        mask = dist_sq <= 1.0
        volume[mask] = np.maximum(volume[mask], b)

    return volume


def create_planar_layer(volume_shape, depth_frac=0.5, pattern='uniform',
                         brightness=1.0, feature_spacing=10):
    """Create a flat fluorescent layer at a single depth.

    Args:
        volume_shape: (ny, nx, n_depths) shape of the volume.
        depth_frac: Fractional depth position in [0, 1].
        pattern: 'uniform', 'grid', or 'checkerboard'.
        brightness: Maximum brightness value.
        feature_spacing: Spacing of pattern features in voxels (for grid/checkerboard).

    Returns:
        3D numpy array.
    """
    volume = np.zeros(volume_shape, dtype='float32')
    ny, nx, nz = volume_shape
    iz = int(np.clip(depth_frac * (nz - 1), 0, nz - 1))

    if pattern == 'uniform':
        volume[:, :, iz] = brightness
    elif pattern == 'grid':
        layer = np.zeros((ny, nx), dtype='float32')
        layer[::feature_spacing, :] = brightness
        layer[:, ::feature_spacing] = brightness
        volume[:, :, iz] = layer
    elif pattern == 'checkerboard':
        yy, xx = np.mgrid[0:ny, 0:nx]
        checker = ((yy // feature_spacing) + (xx // feature_spacing)) % 2
        volume[:, :, iz] = checker.astype('float32') * brightness

    return volume


def create_tilted_plane(volume_shape, brightness=1.0, thickness_voxels=1):
    """Create a fluorescent plane tilted diagonally across the volume.

    The plane goes from (depth=0 at top-left) to (depth=max at bottom-right),
    useful for testing depth continuity in reconstruction.

    Args:
        volume_shape: (ny, nx, n_depths) shape of the volume.
        brightness: Fluorescence intensity.
        thickness_voxels: Thickness of the plane in depth voxels.

    Returns:
        3D numpy array.
    """
    volume = np.zeros(volume_shape, dtype='float32')
    ny, nx, nz = volume_shape

    for iy in range(ny):
        for ix in range(nx):
            # Linear ramp from depth 0 to nz-1 across the diagonal
            frac = (iy / max(ny - 1, 1) + ix / max(nx - 1, 1)) / 2.0
            iz_center = frac * (nz - 1)
            iz_min = max(0, int(iz_center - thickness_voxels / 2))
            iz_max = min(nz - 1, int(iz_center + thickness_voxels / 2))
            volume[iy, ix, iz_min:iz_max + 1] = brightness

    return volume


def create_resolution_target(volume_shape, depth_frac=0.5, brightness=1.0):
    """Create a resolution test target (line pairs at decreasing spacing).

    Args:
        volume_shape: (ny, nx, n_depths) shape of the volume.
        depth_frac: Fractional depth position in [0, 1].
        brightness: Maximum brightness value.

    Returns:
        3D numpy array.
    """
    volume = np.zeros(volume_shape, dtype='float32')
    ny, nx, nz = volume_shape
    iz = int(np.clip(depth_frac * (nz - 1), 0, nz - 1))

    layer = np.zeros((ny, nx), dtype='float32')

    # Create groups of line pairs with decreasing spacing
    spacings = [20, 15, 10, 7, 5, 3, 2]
    x_start = nx // 10
    group_width = (nx - 2 * x_start) // len(spacings)

    for i, spacing in enumerate(spacings):
        x0 = x_start + i * group_width
        x1 = x0 + group_width
        # Draw vertical lines
        for x in range(x0, min(x1, nx)):
            if (x - x0) % (2 * spacing) < spacing:
                y_start = ny // 4
                y_end = 3 * ny // 4
                layer[y_start:y_end, x] = brightness

    volume[:, :, iz] = layer
    return volume


# ---------------------------------------------------------------------------
# Misalignment simulation
# ---------------------------------------------------------------------------

def apply_misalignment(lenslet_centers, misalignment_type, **kwargs):
    """Create a modified copy of LensletCenters with misalignment applied.

    The H/Ht operators depend only on optical parameters (not positions),
    so they can be reused. Only the projection indexing (which maps voxels
    to sensor pixels via lenslet centers) changes.

    Args:
        lenslet_centers: Original LensletCenters dict from sim_setup.
        misalignment_type: One of:
            - 'shift': Global translation. kwargs: dx_px, dy_px
            - 'rotation': Global rotation about center. kwargs: angle_deg
            - 'jitter': Random per-lenslet position error. kwargs: sigma_px, seed
            - 'stretch': Non-uniform scaling. kwargs: scale_x, scale_y

    Returns:
        Modified copy of lenslet_centers dict.
    """
    centers = copy.deepcopy(lenslet_centers)
    px = centers['px']    # shape (n_lenslets_y, n_lenslets_x, 2)
    vox = centers['vox']  # shape (n_lenslets_y, n_lenslets_x, 2)

    if misalignment_type == 'shift':
        dx = kwargs.get('dx_px', 0)
        dy = kwargs.get('dy_px', 0)
        px[:, :, 0] += dy
        px[:, :, 1] += dx
        # Scale shift to voxel space
        vox[:, :, 0] += dy
        vox[:, :, 1] += dx

    elif misalignment_type == 'rotation':
        angle = np.radians(kwargs.get('angle_deg', 0))
        cos_a, sin_a = np.cos(angle), np.sin(angle)
        # Rotate px coords about their center
        for arr in [px, vox]:
            cy = arr[:, :, 0].mean()
            cx = arr[:, :, 1].mean()
            y_centered = arr[:, :, 0] - cy
            x_centered = arr[:, :, 1] - cx
            arr[:, :, 0] = y_centered * cos_a - x_centered * sin_a + cy
            arr[:, :, 1] = y_centered * sin_a + x_centered * cos_a + cx

    elif misalignment_type == 'jitter':
        sigma = kwargs.get('sigma_px', 1.0)
        seed = kwargs.get('seed', None)
        rng = np.random.default_rng(seed)
        noise_px = rng.normal(0, sigma, px.shape).astype(px.dtype)
        noise_vox = rng.normal(0, sigma, vox.shape).astype(vox.dtype)
        px += noise_px
        vox += noise_vox

    elif misalignment_type == 'stretch':
        sx = kwargs.get('scale_x', 1.0)
        sy = kwargs.get('scale_y', 1.0)
        for arr in [px, vox]:
            cy = arr[:, :, 0].mean()
            cx = arr[:, :, 1].mean()
            arr[:, :, 0] = (arr[:, :, 0] - cy) * sy + cy
            arr[:, :, 1] = (arr[:, :, 1] - cx) * sx + cx

    else:
        raise ValueError(f"Unknown misalignment type: {misalignment_type}")

    # Recompute metric from px
    if 'metric' in centers and 'sensorRes' in kwargs:
        sensorRes = kwargs['sensorRes']
        centers['metric'][:, :, 0] = px[:, :, 0] * sensorRes[0]
        centers['metric'][:, :, 1] = px[:, :, 1] * sensorRes[1]

    return centers


# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------

def plot_light_field(lf_image, title="Light Field Image", ax=None, cmap='gray'):
    """Display a light field image.

    Args:
        lf_image: 2D numpy array.
        title: Plot title.
        ax: Optional matplotlib Axes. If None, creates new figure.
        cmap: Colormap name.

    Returns:
        matplotlib Figure (or None if ax was provided).
    """
    fig = None
    if ax is None:
        fig, ax = plt.subplots(1, 1, figsize=(8, 8))

    im = ax.imshow(lf_image, cmap=cmap, origin='upper')
    ax.set_title(title)
    ax.set_xlabel('Sensor x (pixels)')
    ax.set_ylabel('Sensor y (pixels)')
    plt.colorbar(im, ax=ax, shrink=0.8, label='Intensity')
    return fig


def plot_volume_slices(volume, depths_um=None, n_slices=None, title="",
                        cmap='viridis', figsize=None):
    """Display depth slices from a 3D volume.

    Args:
        volume: 3D numpy array (ny, nx, n_depths).
        depths_um: Array of depth values in um (for labels). If None, uses indices.
        n_slices: Number of evenly-spaced slices to show. If None, shows all.
        title: Figure super-title.
        cmap: Colormap name.
        figsize: Figure size tuple.

    Returns:
        matplotlib Figure.
    """
    nz = volume.shape[2]

    if n_slices is None:
        n_slices = min(nz, 7)

    # Select evenly-spaced depth indices
    if nz <= n_slices:
        indices = list(range(nz))
    else:
        indices = np.linspace(0, nz - 1, n_slices, dtype=int).tolist()

    ncols = min(n_slices, 4)
    nrows = int(np.ceil(len(indices) / ncols))

    if figsize is None:
        figsize = (4 * ncols, 3.5 * nrows)

    fig, axes = plt.subplots(nrows, ncols, figsize=figsize, squeeze=False)

    vmin = volume.min()
    vmax = volume.max()

    for i, idx in enumerate(indices):
        row, col = divmod(i, ncols)
        ax = axes[row, col]
        im = ax.imshow(volume[:, :, idx], cmap=cmap, vmin=vmin, vmax=vmax,
                        origin='upper')
        if depths_um is not None:
            ax.set_title(f"z = {depths_um[idx]:.0f} um")
        else:
            ax.set_title(f"Depth index {idx}")
        ax.set_xticks([])
        ax.set_yticks([])

    # Hide unused axes
    for i in range(len(indices), nrows * ncols):
        row, col = divmod(i, ncols)
        axes[row, col].set_visible(False)

    if title:
        fig.suptitle(title, fontsize=14, fontweight='bold')
    fig.tight_layout()
    return fig


def compare_side_by_side(images, titles, suptitle="", cmap='gray', figsize=None):
    """Plot multiple 2D images side by side for comparison.

    Args:
        images: List of 2D numpy arrays.
        titles: List of title strings.
        suptitle: Overall figure title.
        cmap: Colormap name.
        figsize: Figure size tuple.

    Returns:
        matplotlib Figure.
    """
    n = len(images)
    if figsize is None:
        figsize = (5 * n, 5)

    fig, axes = plt.subplots(1, n, figsize=figsize)
    if n == 1:
        axes = [axes]

    for ax, img, t in zip(axes, images, titles):
        im = ax.imshow(img, cmap=cmap, origin='upper')
        ax.set_title(t)
        ax.set_xticks([])
        ax.set_yticks([])
        plt.colorbar(im, ax=ax, shrink=0.8)

    if suptitle:
        fig.suptitle(suptitle, fontsize=14, fontweight='bold')
    fig.tight_layout()
    return fig


def plot_lf_zoomed(lf_image, center=None, radius=50, title="Light Field (zoomed)",
                    ax=None, cmap='gray'):
    """Show a zoomed-in view of the light field to see individual microlens images.

    Args:
        lf_image: 2D numpy array.
        center: (y, x) center of zoom region. None = image center.
        radius: Half-width of zoom region in pixels.
        title: Plot title.
        ax: Optional axes.
        cmap: Colormap.

    Returns:
        matplotlib Figure (or None if ax was provided).
    """
    ny, nx = lf_image.shape
    if center is None:
        center = (ny // 2, nx // 2)

    y0 = max(0, center[0] - radius)
    y1 = min(ny, center[0] + radius)
    x0 = max(0, center[1] - radius)
    x1 = min(nx, center[1] + radius)

    fig = None
    if ax is None:
        fig, ax = plt.subplots(1, 1, figsize=(8, 8))

    cropped = lf_image[y0:y1, x0:x1]
    im = ax.imshow(cropped, cmap=cmap, origin='upper',
                    extent=[x0, x1, y1, y0])
    ax.set_title(title)
    ax.set_xlabel('x (pixels)')
    ax.set_ylabel('y (pixels)')
    plt.colorbar(im, ax=ax, shrink=0.8)
    return fig


# ---------------------------------------------------------------------------
# Convenience: full forward + reconstruct pipeline
# ---------------------------------------------------------------------------

def simulate_and_reconstruct(volume, sim_setup, noise_photons=None,
                              misaligned_centers=None, verbose=True):
    """Run the full simulation pipeline: forward project → reconstruct.

    Args:
        volume: 3D input volume.
        sim_setup: dict from setup_simulation().
        noise_photons: Photon count for Poisson noise (None = no noise).
        misaligned_centers: Modified LensletCenters for forward projection.
            Reconstruction uses ideal centers (simulating unknown misalignment).
        verbose: Print progress.

    Returns:
        dict with 'lf_image', 'reconstructed', 'volume_input'.
    """
    if verbose:
        print("Forward projecting...")
    lf_image = forward_project(volume, sim_setup, noise_photons=noise_photons,
                                lenslet_centers=misaligned_centers)

    if verbose:
        print("Reconstructing...")
    recon = reconstruct(lf_image, sim_setup, verbose=verbose)

    return {
        'lf_image': lf_image,
        'reconstructed': recon,
        'volume_input': volume,
    }


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def get_depths_um(sim_setup):
    """Get the depth values in micrometers for the simulation volume.

    Args:
        sim_setup: dict from setup_simulation().

    Returns:
        numpy array of depth values in um.
    """
    return np.array(sim_setup['Resolution']['depths'])
