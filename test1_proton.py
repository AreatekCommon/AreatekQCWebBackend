#!/usr/bin/env python3
"""
Тестовая утилита для AT32F413 Custom HID Device
VID = 0x2E3C, PID = 0x0019

Поддерживает:
- POWER CAM1-4 (ID 2-5) - OUTPUT 1 байт (0/1)
- COOLER1-3 (ID 6-8) - OUTPUT 1 байт (0-100) - скорость кулеров
- LASER1-2 (ID 9-10) - OUTPUT 1 байт (0/1)
- NEON (ID 11) - OUTPUT 1 байт (0/1)
- SERVO (ID 12) - OUTPUT 2 байта (0-30000) little-endian
- TEMP (ID 13) - INPUT 16 байт (4 x 32-битных значения)
"""

import sys
import struct
from datetime import datetime

try:
    import pywinusb.hid as hid
except ImportError:
    print("Ошибка: библиотека pywinusb не установлена.")
    print("Установите с помощью: pip install pywinusb")
    sys.exit(1)

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except ImportError:
    print("Ошибка: tkinter не установлен")
    sys.exit(1)


class DeviceConfig:
    VENDOR_ID = 0x2E3C
    PRODUCT_ID = 0x0019
    
    # ID отчетов
    REPORT_ID_POWER_CAM1 = 2
    REPORT_ID_POWER_CAM2 = 3
    REPORT_ID_POWER_CAM3 = 4
    REPORT_ID_POWER_CAM4 = 5
    REPORT_ID_COOLER1 = 6
    REPORT_ID_COOLER2 = 7
    REPORT_ID_COOLER3 = 8
    REPORT_ID_LASER1 = 9
    REPORT_ID_LASER2 = 10
    REPORT_ID_NEON = 11
    REPORT_ID_SERVO = 12
    REPORT_ID_TEMP = 13
    
    # Диапазоны
    SERVO_MIN = 0
    SERVO_MAX = 30000
    SERVO_CENTER = 15000
    
    COOLER_MIN = 0
    COOLER_MAX = 100
    
    TEMP_SENSORS_COUNT = 4
    # Формат температуры: int32 little-endian с масштабированием
    # По умолчанию: значение в сотых долях градуса (2530 = 25.30°C)
    TEMP_SCALE = 0.01


class HIDDeviceManager:
    def __init__(self, config: DeviceConfig):
        self.config = config
        self.device = None
        self.is_connected = False
        self.log_callback = None
        
    def find_device(self):
        try:
            filter = hid.HidDeviceFilter(
                vendor_id=self.config.VENDOR_ID,
                product_id=self.config.PRODUCT_ID
            )
            devices = filter.get_devices()
            return devices[0] if devices else None
        except Exception as e:
            if self.log_callback:
                self.log_callback(f"Ошибка поиска: {e}")
            return None
    
    def connect(self) -> bool:
        try:
            self.device = self.find_device()
            if not self.device:
                if self.log_callback:
                    self.log_callback(
                        f"Устройство VID=0x{self.config.VENDOR_ID:04X}, "
                        f"PID=0x{self.config.PRODUCT_ID:04X} не найдено"
                    )
                return False
            
            self.device.open()
            self.is_connected = True
            
            if self.log_callback:
                self.log_callback(
                    f"Подключено: {self.device.product_name} "
                    f"(VID=0x{self.device.vendor_id:04X}, PID=0x{self.device.product_id:04X})"
                )
            return True
            
        except Exception as e:
            if self.log_callback:
                self.log_callback(f"Ошибка подключения: {e}")
            return False
    
    def disconnect(self):
        if self.device and self.is_connected:
            try:
                self.device.close()
            except:
                pass
        self.is_connected = False
        self.device = None
    
    def set_data_handler(self, handler):
        if self.device and self.is_connected:
            self.device.set_raw_data_handler(handler)
    
    def send_output_report(self, report_id: int, data: bytes) -> bool:
        if not self.device or not self.is_connected:
            return False
        
        try:
            report_data = [report_id] + list(data)
            self.device.send_output_report(report_data)
            return True
        except Exception as e:
            if self.log_callback:
                self.log_callback(f"Ошибка отправки (ID={report_id}): {e}")
            return False
    
    def is_plugged(self) -> bool:
        return self.device is not None and self.is_connected and self.device.is_plugged()


class HIDControlApp:
    def __init__(self):
        self.config = DeviceConfig()
        self.device_manager = HIDDeviceManager(self.config)
        self.device_manager.log_callback = self.log_message
        
        # Состояния выходов
        self.output_states = {
            2: False, 3: False, 4: False, 5: False,  # POWER CAM
            9: False, 10: False,  # LASER
            11: False  # NEON
        }
        # Скорости кулеров (0-100)
        self.cooler_speeds = {6: 0, 7: 0, 8: 0}
        
        self.temp_values = [0.0] * self.config.TEMP_SENSORS_COUNT
        self.refresh_paused = False
        self.temp_format = "int32_le"  # Формат температуры
        
        # Инициализация атрибутов виджетов
        self.root = None
        self.cam_buttons = {}
        self.cooler_sliders = {}
        self.cooler_labels = {}
        self.laser_buttons = {}
        self.neon_button = None
        self.servo_slider = None
        self.servo_spinbox = None
        self.servo_value_label = None
        self.servo_status_label = None
        self.temp_labels = []
        self.temp_progress = []
        self.log_text = None
        self.status_label = None
        self.connect_btn = None
        self.refresh_btn = None
        self.raw_data_checkbox = None
        self.show_raw_data = None
        self.last_update_label = None
        self.temp_format_var = None
        self.temp_format_combo = None
        
        self.setup_styles()
        self.create_window()
        self.update_connection_status()
    
    def setup_styles(self):
        self.button_styles = {
            'on': {'bg': '#2ecc71', 'fg': 'white', 'text': 'ВКЛ'},
            'off': {'bg': '#e74c3c', 'fg': 'white', 'text': 'ВЫКЛ'},
        }
    
    def create_window(self):
        self.root = tk.Tk()
        self.root.title("AT32F413 HID Device Controller")
        self.root.geometry("950x850")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.show_raw_data = tk.BooleanVar(value=True)
        self.temp_format_var = tk.StringVar(value="int32_le (32-bit int *0.01)")
        
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        self.create_connection_panel(main_frame)
        
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        self.create_output_tab()
        self.create_servo_tab()
        self.create_temp_tab()
        self.create_log_tab()
    
    def create_connection_panel(self, parent):
        conn_frame = ttk.LabelFrame(parent, text="Подключение", padding="5")
        conn_frame.pack(fill=tk.X, pady=(0, 10))
        
        info_text = f"VID: 0x{self.config.VENDOR_ID:04X} | PID: 0x{self.config.PRODUCT_ID:04X}"
        ttk.Label(conn_frame, text=info_text).pack(side=tk.LEFT, padx=5)
        
        self.connect_btn = ttk.Button(
            conn_frame, text="Подключить",
            command=self.toggle_connection, width=15
        )
        self.connect_btn.pack(side=tk.RIGHT, padx=5)
        
        self.status_label = ttk.Label(conn_frame, text="● Отключено", foreground="red")
        self.status_label.pack(side=tk.RIGHT, padx=10)
    
    def create_output_tab(self):
        tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(tab, text="Управление")
        
        # POWER CAM (ON/OFF)
        cam_frame = ttk.LabelFrame(tab, text="POWER CAM (0=ВЫКЛ, 1=ВКЛ)", padding="10")
        cam_frame.pack(fill=tk.X, pady=5)
        
        cam_names = {2: "CAM1", 3: "CAM2", 4: "CAM3", 5: "CAM4"}
        for col, (rid, name) in enumerate(cam_names.items()):
            btn = tk.Button(
                cam_frame, text=f"🔴 {name}",
                width=12, height=2,
                command=lambda r=rid: self.toggle_output(r)
            )
            btn.grid(row=0, column=col, padx=5, pady=5)
            self.cam_buttons[rid] = btn
            self.update_button_style(btn, False)
        
        # COOLER (0-100)
        cooler_frame = ttk.LabelFrame(tab, text="COOLER (0-100%)", padding="10")
        cooler_frame.pack(fill=tk.X, pady=5)
        
        cooler_names = {6: "COOLER1", 7: "COOLER2", 8: "COOLER3"}
        for i, (rid, name) in enumerate(cooler_names.items()):
            # Фрейм для каждого кулера
            cf = ttk.Frame(cooler_frame)
            cf.pack(fill=tk.X, pady=5)
            
            ttk.Label(cf, text=f"{name}:").pack(side=tk.LEFT, padx=5)
            
            # Слайдер
            slider = ttk.Scale(
                cf,
                from_=self.config.COOLER_MIN,
                to=self.config.COOLER_MAX,
                orient=tk.HORIZONTAL,
                length=200,
                command=lambda v, r=rid: self.on_cooler_change(r, v)
            )
            slider.set(0)
            slider.pack(side=tk.LEFT, padx=5)
            
            # Значение (%)
            label = ttk.Label(cf, text="0%", width=6)
            label.pack(side=tk.LEFT, padx=5)
            self.cooler_labels[rid] = label
            
            # Spinbox для точного ввода
            spinbox = tk.Spinbox(
                cf,
                from_=self.config.COOLER_MIN,
                to=self.config.COOLER_MAX,
                width=5,
                command=lambda r=rid: self.on_cooler_spin(r)
            )
            spinbox.pack(side=tk.LEFT, padx=5)
            self.cooler_sliders[rid] = (slider, spinbox)
        
        # LASER (ON/OFF)
        laser_frame = ttk.LabelFrame(tab, text="LASER (0=ВЫКЛ, 1=ВКЛ)", padding="10")
        laser_frame.pack(fill=tk.X, pady=5)
        
        for i, rid in enumerate([9, 10]):
            btn = tk.Button(
                laser_frame, text=f"⚡ LASER{i+1}",
                width=12, height=2,
                command=lambda r=rid: self.toggle_output(r)
            )
            btn.grid(row=0, column=i, padx=5, pady=5)
            self.laser_buttons[rid] = btn
            self.update_button_style(btn, False)
        
        # NEON (ON/OFF)
        neon_frame = ttk.LabelFrame(tab, text="NEON (0=ВЫКЛ, 1=ВКЛ)", padding="10")
        neon_frame.pack(fill=tk.X, pady=5)
        
        self.neon_button = tk.Button(
            neon_frame, text="💡 NEON",
            width=12, height=2,
            command=lambda: self.toggle_output(11)
        )
        self.neon_button.pack()
        self.update_button_style(self.neon_button, False)
        
        # ALL ON/OFF (для дискретных выходов, без кулеров)
        all_btn_frame = ttk.Frame(tab)
        all_btn_frame.pack(fill=tk.X, pady=10)
        
        all_on_btn = ttk.Button(all_btn_frame, text="ВСЕ ВКЛ (CAM/LASER/NEON)", command=self.all_on, width=25)
        all_on_btn.pack(side=tk.LEFT, padx=10)
        
        all_off_btn = ttk.Button(all_btn_frame, text="ВСЕ ВЫКЛ (CAM/LASER/NEON)", command=self.all_off, width=25)
        all_off_btn.pack(side=tk.RIGHT, padx=10)
    
    def create_servo_tab(self):
        tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(tab, text="Сервопривод")
        
        servo_frame = ttk.LabelFrame(tab, text="Управление сервоприводом", padding="15")
        servo_frame.pack(fill=tk.BOTH, expand=True)
        
        info_label = ttk.Label(
            servo_frame,
            text=f"Диапазон: {self.config.SERVO_MIN} - {self.config.SERVO_MAX} (0-180°)",
            foreground="gray"
        )
        info_label.pack(pady=5)
        
        self.servo_value_label = ttk.Label(servo_frame, text="Позиция: 0", font=('Arial', 14))
        self.servo_value_label.pack(pady=5)
        
        self.servo_slider = ttk.Scale(
            servo_frame,
            from_=self.config.SERVO_MIN,
            to=self.config.SERVO_MAX,
            orient=tk.HORIZONTAL,
            length=400
        )
        self.servo_slider.set(0)
        self.servo_slider.pack(pady=10)
        self.servo_slider.configure(command=self.on_servo_preview)
        
        spin_frame = ttk.Frame(servo_frame)
        spin_frame.pack(pady=10)
        ttk.Label(spin_frame, text="Точное значение:").pack(side=tk.LEFT, padx=5)
        
        self.servo_spinbox = tk.Spinbox(
            spin_frame,
            from_=self.config.SERVO_MIN,
            to=self.config.SERVO_MAX,
            width=8
        )
        self.servo_spinbox.pack(side=tk.LEFT, padx=5)
        self.servo_spinbox.bind('<KeyRelease>', self.on_spinbox_preview)
        
        send_frame = ttk.Frame(servo_frame)
        send_frame.pack(pady=15)
        
        send_btn = ttk.Button(send_frame, text="📤 ОТПРАВИТЬ ПОЗИЦИЮ", command=self.send_servo_from_ui, width=25)
        send_btn.pack()
        
        self.servo_status_label = ttk.Label(servo_frame, text="", foreground="gray")
        self.servo_status_label.pack(pady=5)
        
        preset_frame = ttk.LabelFrame(tab, text="Пресеты", padding="10")
        preset_frame.pack(fill=tk.X, pady=10)
        
        preset_buttons_frame = ttk.Frame(preset_frame)
        preset_buttons_frame.pack()
        
        for name, value in [("MIN (0°)", 0), ("CENTER (90°)", self.config.SERVO_CENTER), ("MAX (180°)", self.config.SERVO_MAX)]:
            btn = ttk.Button(preset_buttons_frame, text=name, command=lambda v=value: self.set_servo_preset(v))
            btn.pack(side=tk.LEFT, padx=10, expand=True)
    
    def create_temp_tab(self):
        tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(tab, text="Температура")
        
        # Панель настроек формата
        settings_frame = ttk.LabelFrame(tab, text="Настройки формата данных", padding="10")
        settings_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(settings_frame, text="Формат температуры:").pack(side=tk.LEFT, padx=5)
        
        self.temp_format_combo = ttk.Combobox(
            settings_frame,
            textvariable=self.temp_format_var,
            values=[
                "int32_le (32-bit int *0.01)",
                "int32_be (32-bit int *0.01)",
                "float_le (Little-Endian Float)",
                "float_be (Big-Endian Float)"
            ],
            state="readonly",
            width=35
        )
        self.temp_format_combo.pack(side=tk.LEFT, padx=5)
        self.temp_format_combo.bind('<<ComboboxSelected>>', self.on_temp_format_change)
        
        ttk.Label(settings_frame, text="(выберите правильный формат для вашего устройства)", foreground="gray").pack(side=tk.LEFT, padx=5)
        
        info_frame = ttk.Frame(tab)
        info_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(info_frame, text="📊 Один HID отчет (ID=13) содержит данные всех 4 датчиков (4 x 32-битных значения)", foreground="blue").pack()
        
        raw_frame = ttk.Frame(tab)
        raw_frame.pack(fill=tk.X, pady=5)
        
        self.raw_data_checkbox = ttk.Checkbutton(
            raw_frame,
            text="Показывать сырые данные в логе",
            variable=self.show_raw_data
        )
        self.raw_data_checkbox.pack(side=tk.LEFT)
        
        ttk.Label(raw_frame, text="(HEX дамп принятых пакетов)", foreground="gray").pack(side=tk.LEFT, padx=5)
        
        for i in range(self.config.TEMP_SENSORS_COUNT):
            frame = ttk.LabelFrame(tab, text=f"Датчик {i+1}", padding="10")
            frame.pack(fill=tk.X, pady=5)
            
            temp_label = ttk.Label(frame, text="-- °C", font=('Arial', 16, 'bold'))
            temp_label.pack(pady=5)
            self.temp_labels.append(temp_label)
            
            progress = ttk.Progressbar(frame, orient=tk.HORIZONTAL, length=300, mode='determinate', maximum=500)
            progress.pack(pady=5)
            self.temp_progress.append(progress)
            
            scale_frame = ttk.Frame(frame)
            scale_frame.pack(fill=tk.X, pady=5)
            ttk.Label(scale_frame, text="0°C").pack(side=tk.LEFT)
            ttk.Label(scale_frame, text="25°C").pack(side=tk.LEFT, expand=True)
            ttk.Label(scale_frame, text="50°C").pack(side=tk.RIGHT)
        
        self.last_update_label = ttk.Label(tab, text="", foreground="gray")
        self.last_update_label.pack(pady=5)
        
        control_frame = ttk.Frame(tab)
        control_frame.pack(pady=10)
        
        self.refresh_btn = ttk.Button(control_frame, text="⏸ Приостановить обновление", command=self.toggle_refresh)
        self.refresh_btn.pack(side=tk.LEFT, padx=5)
        
        request_btn = ttk.Button(control_frame, text="🔄 Запросить данные", command=self.request_temperature)
        request_btn.pack(side=tk.LEFT, padx=5)
        
        test_btn = ttk.Button(control_frame, text="🔍 Тестовая распаковка", command=self.test_temp_parsing)
        test_btn.pack(side=tk.LEFT, padx=5)
    
    def create_log_tab(self):
        tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(tab, text="Лог")
        
        log_frame = ttk.Frame(tab)
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(log_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.log_text = tk.Text(log_frame, wrap=tk.WORD, yscrollcommand=scrollbar.set, font=('Courier New', 9), height=15)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.log_text.yview)
        
        log_control = ttk.Frame(tab)
        log_control.pack(fill=tk.X, pady=5)
        
        clear_btn = ttk.Button(log_control, text="Очистить лог", command=self.clear_log)
        clear_btn.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(log_control, text="COOLER: 0-100% | SERVO: 0-30000 (16-bit LE) | TEMP: 4x32-bit", foreground="green").pack(side=tk.LEFT, padx=10)
    
    # ===== Логика работы с устройством =====
    
    def toggle_connection(self):
        if self.device_manager.is_connected:
            self.disconnect_device()
        else:
            self.connect_device()
    
    def connect_device(self):
        if self.device_manager.connect():
            self.device_manager.set_data_handler(self.on_data_received)
            self.status_label.config(text="● Подключено", foreground="green")
            self.connect_btn.config(text="Отключить")
            self.log_message("Устройство подключено")
        else:
            messagebox.showerror(
                "Ошибка подключения",
                f"Не удалось подключиться к устройству\nVID: 0x{self.config.VENDOR_ID:04X}, PID: 0x{self.config.PRODUCT_ID:04X}"
            )
    
    def disconnect_device(self):
        self.device_manager.disconnect()
        self.status_label.config(text="● Отключено", foreground="red")
        self.connect_btn.config(text="Подключить")
        self.log_message("Устройство отключено")
    
    def update_connection_status(self):
        if self.device_manager.is_connected and not self.device_manager.is_plugged():
            self.disconnect_device()
            self.log_message("Потеряно соединение с устройством")
        
        if self.root:
            self.root.after(1000, self.update_connection_status)
    
    def toggle_output(self, report_id: int):
        if not self.device_manager.is_connected:
            self.log_message("Ошибка: устройство не подключено")
            return
        
        new_state = not self.output_states.get(report_id, False)
        data = bytes([1 if new_state else 0])
        
        if self.device_manager.send_output_report(report_id, data):
            self.output_states[report_id] = new_state
            self.update_button_style_by_id(report_id, new_state)
            state_str = "ВКЛ" if new_state else "ВЫКЛ"
            self.log_message(f"Report ID {report_id} -> {state_str}")
    
    def send_cooler_speed(self, report_id: int, speed: int):
        if not self.device_manager.is_connected:
            self.log_message("Ошибка: устройство не подключено")
            return
        
        speed = max(self.config.COOLER_MIN, min(speed, self.config.COOLER_MAX))
        data = bytes([speed])
        
        if self.device_manager.send_output_report(report_id, data):
            self.cooler_speeds[report_id] = speed
            self.log_message(f"COOLER ID {report_id} -> скорость {speed}%")
    
    def on_cooler_change(self, report_id: int, value):
        speed = int(float(value))
        slider, spinbox = self.cooler_sliders[report_id]
        
        # Обновляем spinbox
        spinbox.delete(0, tk.END)
        spinbox.insert(0, str(speed))
        
        # Обновляем метку
        if report_id in self.cooler_labels:
            self.cooler_labels[report_id].config(text=f"{speed}%")
        
        # Отправляем новую скорость
        self.send_cooler_speed(report_id, speed)
    
    def on_cooler_spin(self, report_id: int):
        slider, spinbox = self.cooler_sliders[report_id]
        try:
            speed = int(spinbox.get())
            speed = max(self.config.COOLER_MIN, min(speed, self.config.COOLER_MAX))
            slider.set(speed)
            if report_id in self.cooler_labels:
                self.cooler_labels[report_id].config(text=f"{speed}%")
            self.send_cooler_speed(report_id, speed)
        except ValueError:
            pass
    
    def update_button_style_by_id(self, report_id: int, state: bool):
        if report_id in self.cam_buttons:
            self.update_button_style(self.cam_buttons[report_id], state)
        elif report_id in self.laser_buttons:
            self.update_button_style(self.laser_buttons[report_id], state)
        elif report_id == 11 and self.neon_button:
            self.update_button_style(self.neon_button, state)
    
    def update_button_style(self, button: tk.Button, state: bool):
        if state:
            button.config(bg=self.button_styles['on']['bg'], fg=self.button_styles['on']['fg'], text=self.button_styles['on']['text'])
        else:
            button.config(bg=self.button_styles['off']['bg'], fg=self.button_styles['off']['fg'], text=self.button_styles['off']['text'])
    
    def all_on(self):
        if not self.device_manager.is_connected:
            self.log_message("Ошибка: устройство не подключено")
            return
        for rid in [2, 3, 4, 5, 9, 10, 11]:
            if not self.output_states.get(rid, False):
                self.toggle_output(rid)
    
    def all_off(self):
        if not self.device_manager.is_connected:
            self.log_message("Ошибка: устройство не подключено")
            return
        for rid in [2, 3, 4, 5, 9, 10, 11]:
            if self.output_states.get(rid, False):
                self.toggle_output(rid)
    
    # ===== Логика сервопривода =====
    
    def on_servo_preview(self, value):
        pos = int(float(value))
        if self.servo_spinbox:
            self.servo_spinbox.delete(0, tk.END)
            self.servo_spinbox.insert(0, str(pos))
        if self.servo_value_label:
            self.servo_value_label.config(text=f"Позиция: {pos} (предпросмотр)")
    
    def on_spinbox_preview(self, event=None):
        try:
            pos = int(self.servo_spinbox.get())
            pos = max(self.config.SERVO_MIN, min(pos, self.config.SERVO_MAX))
            if self.servo_slider:
                self.servo_slider.set(pos)
            if self.servo_value_label:
                self.servo_value_label.config(text=f"Позиция: {pos} (предпросмотр)")
        except ValueError:
            pass
    
    def send_servo_from_ui(self):
        if not self.device_manager.is_connected:
            self.log_message("Ошибка: устройство не подключено")
            self.update_servo_status("❌ Устройство не подключено", "red")
            return
        
        try:
            position = int(self.servo_spinbox.get())
        except ValueError:
            position = int(self.servo_slider.get())
        
        position = max(self.config.SERVO_MIN, min(position, self.config.SERVO_MAX))
        data = struct.pack('<H', position)
        
        if self.device_manager.send_output_report(self.config.REPORT_ID_SERVO, data):
            self.servo_value_label.config(text=f"Позиция: {position} (отправлено)")
            self.log_message(f"Сервопривод: отправлена позиция {position}")
            self.update_servo_status(f"✓ Отправлено: {position}", "green")
            
            if self.root:
                self.root.after(2000, lambda: self.update_servo_status("", "gray"))
                self.root.after(2000, lambda: self.servo_value_label.config(text=f"Позиция: {position}"))
        else:
            self.update_servo_status("❌ Ошибка отправки", "red")
    
    def set_servo_preset(self, position: int):
        position = max(self.config.SERVO_MIN, min(position, self.config.SERVO_MAX))
        
        if self.servo_slider:
            self.servo_slider.set(position)
        if self.servo_spinbox:
            self.servo_spinbox.delete(0, tk.END)
            self.servo_spinbox.insert(0, str(position))
        if self.servo_value_label:
            self.servo_value_label.config(text=f"Позиция: {position}")
        
        if self.device_manager.is_connected:
            data = struct.pack('<H', position)
            if self.device_manager.send_output_report(self.config.REPORT_ID_SERVO, data):
                self.log_message(f"Сервопривод: пресет {position}")
                self.update_servo_status(f"✓ Пресет: {position}", "green")
                if self.root:
                    self.root.after(2000, lambda: self.update_servo_status("", "gray"))
            else:
                self.update_servo_status("❌ Ошибка отправки", "red")
        else:
            self.log_message("Ошибка: устройство не подключено")
            self.update_servo_status("❌ Устройство не подключено", "red")
    
    def update_servo_status(self, message: str, color: str):
        if self.servo_status_label:
            self.servo_status_label.config(text=message, foreground=color)
    
    # ===== Логика температуры =====
    
    def on_temp_format_change(self, event=None):
        format_map = {
            "int32_le (32-bit int *0.01)": "int32_le",
            "int32_be (32-bit int *0.01)": "int32_be",
            "float_le (Little-Endian Float)": "float_le",
            "float_be (Big-Endian Float)": "float_be"
        }
        self.temp_format = format_map.get(self.temp_format_var.get(), "int32_le")
        self.log_message(f"Формат температуры изменен на: {self.temp_format_var.get()}")
    
    def parse_temperature_data(self, payload):
        temp_values = []
        
        if self.temp_format == "float_be":
            for i in range(4):
                float_bytes = payload[i*4:(i+1)*4]
                temp_c = struct.unpack('>f', float_bytes)[0]
                temp_values.append(temp_c)
        elif self.temp_format == "float_le":
            for i in range(4):
                float_bytes = payload[i*4:(i+1)*4]
                temp_c = struct.unpack('<f', float_bytes)[0]
                temp_values.append(temp_c)
        elif self.temp_format == "int32_be":
            int_values = struct.unpack('>IIII', payload[:16])
            temp_values = [v * self.config.TEMP_SCALE for v in int_values]
        else:  # int32_le (по умолчанию)
            int_values = struct.unpack('<IIII', payload[:16])
            temp_values = [v * self.config.TEMP_SCALE for v in int_values]
        
        return temp_values
    
    def request_temperature(self):
        if not self.device_manager.is_connected:
            self.log_message("Ошибка: устройство не подключено")
            return
        self.log_message("Ожидание данных температуры от устройства...")
    
    def toggle_refresh(self):
        self.refresh_paused = not self.refresh_paused
        if self.refresh_paused:
            self.refresh_btn.config(text="▶ Возобновить обновление")
            self.log_message("Обновление температуры приостановлено")
        else:
            self.refresh_btn.config(text="⏸ Приостановить обновление")
            self.log_message("Обновление температуры возобновлено")
    
    def test_temp_parsing(self):
        if hasattr(self, 'last_temp_payload') and self.last_temp_payload:
            self.log_message("🔍 Тестовая распаковка последних данных:")
            
            formats = [
                ("int32_le (32-bit int *0.01)", "int32_le"),
                ("int32_be (32-bit int *0.01)", "int32_be"),
                ("float_le (Little-Endian Float)", "float_le"),
                ("float_be (Big-Endian Float)", "float_be")
            ]
            
            for format_name, format_type in formats:
                try:
                    if format_type == "float_be":
                        values = []
                        for i in range(4):
                            float_bytes = self.last_temp_payload[i*4:(i+1)*4]
                            values.append(struct.unpack('>f', float_bytes)[0])
                    elif format_type == "float_le":
                        values = []
                        for i in range(4):
                            float_bytes = self.last_temp_payload[i*4:(i+1)*4]
                            values.append(struct.unpack('<f', float_bytes)[0])
                    elif format_type == "int32_be":
                        int_values = struct.unpack('>IIII', self.last_temp_payload[:16])
                        values = [v * 0.01 for v in int_values]
                    else:  # int32_le
                        int_values = struct.unpack('<IIII', self.last_temp_payload[:16])
                        values = [v * 0.01 for v in int_values]
                    
                    temp_str = " | ".join([f"{v:.2f}°C" for v in values])
                    self.log_message(f"   {format_name}: {temp_str}")
                except Exception as e:
                    self.log_message(f"   {format_name}: Ошибка - {e}")
        else:
            self.log_message("Нет полученных данных для теста. Дождитесь приема данных от устройства.")
    
    def format_hex_dump(self, data) -> str:
        return ' '.join(f'{b:02X}' for b in data)
    
    def on_data_received(self, data):
        if not data or len(data) == 0:
            return
        
        if not isinstance(data, bytes):
            try:
                data = bytes(data)
            except:
                data = bytes(list(data))
        
        report_id = data[0]
        payload = data[1:]
        
        if report_id == self.config.REPORT_ID_TEMP:
            hex_dump = self.format_hex_dump(data)
            self.last_temp_payload = payload
            
            if len(payload) >= 16:
                try:
                    temp_values = self.parse_temperature_data(payload)
                    
                    parsed_values = [f"T{i+1}={v:.2f}°C" for i, v in enumerate(temp_values)]
                    parsed_str = " | ".join(parsed_values)
                    
                    if self.show_raw_data.get():
                        self.log_message(f"🌡️ TEMP RAW: [{hex_dump}]")
                        self.log_message(f"📊 TEMP PARSED ({self.temp_format_var.get()}): {parsed_str}")
                    else:
                        self.log_message(f"📊 TEMP: {parsed_str}")
                    
                    if self.root:
                        self.root.after(0, lambda rv=temp_values: self.update_temperatures(rv))
                    
                except Exception as e:
                    self.log_message(f"❌ Ошибка распаковки температуры: {e}")
                    self.log_message(f"   Сырые данные: [{hex_dump}]")
            else:
                self.log_message(f"⚠️ Получен короткий температурный пакет: {len(payload)} байт (ожидалось 16)")
                self.log_message(f"   Сырые данные: [{hex_dump}]")
        else:
            hex_dump = self.format_hex_dump(data)
            self.log_message(f"📦 Получено (ID={report_id}): [{hex_dump}]")
    
    def update_temperatures(self, temp_values):
        if self.refresh_paused:
            return
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        for i, temp_c in enumerate(temp_values):
            if i >= self.config.TEMP_SENSORS_COUNT:
                break
            
            self.temp_values[i] = temp_c
            
            if i < len(self.temp_labels):
                self.temp_labels[i].config(text=f"{temp_c:.2f} °C")
            
            if i < len(self.temp_progress):
                progress_value = min(int(temp_c * 10), 500)
                self.temp_progress[i]['value'] = progress_value
                
                if temp_c > 45:
                    self.temp_labels[i].config(foreground="red")
                elif temp_c > 30:
                    self.temp_labels[i].config(foreground="orange")
                else:
                    self.temp_labels[i].config(foreground="green")
        
        self.last_update_label.config(text=f"Последнее обновление: {timestamp}")
    
    def log_message(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        if self.root:
            self.root.after(0, lambda: self._append_log(f"[{timestamp}] {message}\n"))
    
    def _append_log(self, text: str):
        if self.log_text:
            self.log_text.insert(tk.END, text)
            self.log_text.see(tk.END)
    
    def clear_log(self):
        if self.log_text:
            self.log_text.delete(1.0, tk.END)
    
    def on_closing(self):
        self.device_manager.disconnect()
        if self.root:
            self.root.destroy()
    
    def run(self):
        if self.root:
            self.root.mainloop()


if __name__ == "__main__":
    app = HIDControlApp()
    app.run()