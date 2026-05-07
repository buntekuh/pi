# cmod_a7.xdc — Titania / M56 constraints for Cmod A7-35T

# 12 MHz clock
set_property PACKAGE_PIN L17 [get_ports clk]
set_property IOSTANDARD LVCMOS33 [get_ports clk]
create_clock -period 83.33 [get_ports clk]

# LEDs
set_property PACKAGE_PIN A17 [get_ports {led[0]}]
set_property PACKAGE_PIN C16 [get_ports {led[1]}]
set_property IOSTANDARD LVCMOS33 [get_ports {led[0]}]
set_property IOSTANDARD LVCMOS33 [get_ports {led[1]}]

# Buttons (active high — BTN0 = reset)
set_property PACKAGE_PIN A18 [get_ports {btn[0]}]
set_property PACKAGE_PIN B18 [get_ports {btn[1]}]
set_property IOSTANDARD LVCMOS33 [get_ports {btn[0]}]
set_property IOSTANDARD LVCMOS33 [get_ports {btn[1]}]

# USB-UART via FT2232HQ
set_property PACKAGE_PIN J17 [get_ports uart_rxd_in]
set_property PACKAGE_PIN J18 [get_ports uart_txd_out]
set_property IOSTANDARD LVCMOS33 [get_ports uart_rxd_in]
set_property IOSTANDARD LVCMOS33 [get_ports uart_txd_out]
