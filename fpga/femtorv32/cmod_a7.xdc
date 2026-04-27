# cmod_a7.xdc — Titania / FemtoRV32 constraints for Cmod A7-35T
# Onboard USB-UART via FT2232HQ (no external adapter needed).

# 12 MHz clock
set_property PACKAGE_PIN L17 [get_ports CLK]
set_property IOSTANDARD LVCMOS33 [get_ports CLK]
create_clock -period 83.33 [get_ports CLK]

# LEDs
set_property PACKAGE_PIN A17 [get_ports {LEDS[0]}]
set_property PACKAGE_PIN C16 [get_ports {LEDS[1]}]
set_property IOSTANDARD LVCMOS33 [get_ports {LEDS[0]}]
set_property IOSTANDARD LVCMOS33 [get_ports {LEDS[1]}]

# Reset button (BTN0, active high)
set_property PACKAGE_PIN A18 [get_ports RESET]
set_property IOSTANDARD LVCMOS33 [get_ports RESET]

# USB-UART (FT2232HQ channel B)
# J17 = uart_txd_in  = data arriving from PC  → our RXD
# J18 = uart_rxd_out = data going to PC       → our TXD
set_property PACKAGE_PIN J17 [get_ports RXD]
set_property PACKAGE_PIN J18 [get_ports TXD]
set_property IOSTANDARD LVCMOS33 [get_ports RXD]
set_property IOSTANDARD LVCMOS33 [get_ports TXD]
