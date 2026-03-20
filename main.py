from t46 import T46
from m56 import M56

terminal = T46()
computer = M56(terminal)

terminal.connect(computer)
computer.connect()

while terminal.running:
    terminal.poll()
