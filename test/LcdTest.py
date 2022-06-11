from senseurspassifs_rpi.RPiTWI import LcdHandler

lcd_handler = LcdHandler()
lcd_handler.initialise()

lcd_handler.lcd_string('Allo', LcdHandler.LCD_LINE_1)
lcd_handler.lcd_string('Heure du jour', LcdHandler.LCD_LINE_2)
