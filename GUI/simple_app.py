import sys
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton
from PySide6.QtCore import Qt

class SimpleAdder(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("Simple Adder")
        self.setGeometry(100, 100, 300, 200)
        
        layout = QVBoxLayout()
        
        # Input A
        layout.addWidget(QLabel("A:"))
        self.input_a = QLineEdit()
        layout.addWidget(self.input_a)
        
        # Input B
        layout.addWidget(QLabel("B:"))
        self.input_b = QLineEdit()
        layout.addWidget(self.input_b)
        
        # Button
        self.button = QPushButton("Add")
        self.button.clicked.connect(self.on_add)
        layout.addWidget(self.button)
        
        # Output
        layout.addWidget(QLabel("Result:"))
        self.output = QLabel("0")
        layout.addWidget(self.output)
        
        self.setLayout(layout)
    
    def on_add(self):
        try:
            a = float(self.input_a.text())
            b = float(self.input_b.text())
            result = a + b
            self.output.setText(str(result))
        except ValueError:
            self.output.setText("Invalid input")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SimpleAdder()
    window.show()
    sys.exit(app.exec())