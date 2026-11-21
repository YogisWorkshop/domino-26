import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from main_window import MainWindow
import config

APP_STYLESHEET = """
QPushButton {
    min-height: 40px;
    min-width: 80px;
    font-size: 20px;
}
QLineEdit, QSpinBox, QComboBox {
    min-height: 40px;
    font-size: 20px;
}
QLabel {
    font-size: 20px;
}
QTabBar::tab {
    font-size: 20px;
    min-height: 40px;
    min-width: 80px;
}
QSpinBox::up-button, QSpinBox::down-button {
    width: 40px;
    height: 20px;
}
QCheckBox {
    font-size: 20px;
    min-height: 40px;
}
QCheckBox::indicator {
    width: 32px;
    height: 32px;
}
QScrollBar:vertical {
    width: 30px;
}
QScrollBar::handle:vertical {
    background: #999999;
    min-height: 40px;
    border-radius: 6px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Domino-26")
    app.setDesktopFileName("domino-26")
    app.setWindowIcon(QIcon(config.APP_ICON_PATH))
    app.setStyleSheet(APP_STYLESHEET)

    window = MainWindow()
    if config.FULLSCREEN:
        window.showFullScreen()
    else: 
        window.show()          

    sys.exit(app.exec())

if __name__ == "__main__":
    main()

