import json
import queue
import re
import struct
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from salinity_conversion import konversi_salinitas
from ph_conversion import adc_ke_ph

from pyrf24 import RF24, RF24_250KBPS, RF24_PA_LOW


latest_telemetry = {}
tunnel_widgets = {}
selected_device_id = None
ROLE_OPTIONS = ("FRONT", "MIDDLE", "BACK")
latest_windspeed = None
COLORS = {
    "background": "#eaf6ff",
    "panel": "#d9efff",
    "accent": "#9ed8f5",
    "accent_active": "#78c5eb",
    "text": "#16324f",
    "white": "#ffffff"
}

root = tk.Tk()
root.title("Smart Salt Tunnel")
root.geometry("1024x600")
root.configure(bg=COLORS["background"])
root.option_add("*Background", COLORS["panel"])
root.option_add("*Foreground", COLORS["text"])
root.option_add("*Button.Background", COLORS["accent"])
root.option_add("*Button.Foreground", COLORS["text"])
root.option_add("*Button.ActiveBackground", COLORS["accent_active"])
root.option_add("*Button.ActiveForeground", COLORS["text"])
style = ttk.Style(root)
style.configure(
    "Blue.Vertical.TScrollbar",
    troughcolor=COLORS["panel"],
    background=COLORS["accent"],
    arrowcolor=COLORS["text"]
)

main_frame = tk.Frame(root, bg=COLORS["background"])
main_frame.pack(fill="both", expand=True, padx=20, pady=10)

sidebar = tk.LabelFrame(
    main_frame,
    text="Tunnels",
    font=("Arial", 14, "bold"),
    padx=8,
    pady=8,
    width=180
)
sidebar.pack(side="left", fill="y")
sidebar.pack_propagate(False)

add_tunnel_button = tk.Button(
    sidebar,
    text="+ Add tunnel",
    font=("Arial", 12, "bold"),
    command=lambda: open_add_tunnel_dialog()
)
add_tunnel_button.pack(fill="x", pady=(0, 10))

tunnel_list_canvas = tk.Canvas(
    sidebar, highlightthickness=0, bg=COLORS["panel"]
)
tunnel_list_scrollbar = ttk.Scrollbar(
    sidebar,
    orient="vertical",
    command=tunnel_list_canvas.yview,
    style="Blue.Vertical.TScrollbar"
)
tunnel_list_frame = tk.Frame(tunnel_list_canvas, bg=COLORS["panel"])
tunnel_list_window = tunnel_list_canvas.create_window(
    (0, 0), window=tunnel_list_frame, anchor="nw"
)
tunnel_list_canvas.configure(yscrollcommand=tunnel_list_scrollbar.set)
tunnel_list_canvas.pack(side="left", fill="both", expand=True)
tunnel_list_scrollbar.pack(side="right", fill="y")
tunnel_list_frame.bind(
    "<Configure>",
    lambda event: tunnel_list_canvas.configure(
        scrollregion=tunnel_list_canvas.bbox("all")
    )
)
tunnel_list_canvas.bind(
    "<Configure>",
    lambda event: tunnel_list_canvas.itemconfigure(
        tunnel_list_window, width=event.width
    )
)

def scroll_tunnel_list(event):
    event_num = getattr(event, "num", None)
    if event_num == 4:
        tunnel_list_canvas.yview_scroll(-1, "units")
    elif event_num == 5:
        tunnel_list_canvas.yview_scroll(1, "units")
    elif getattr(event, "delta", 0):
        tunnel_list_canvas.yview_scroll(-int(event.delta / 120), "units")

tunnel_list_canvas.bind("<MouseWheel>", scroll_tunnel_list)
tunnel_list_canvas.bind("<Button-4>", scroll_tunnel_list)
tunnel_list_canvas.bind("<Button-5>", scroll_tunnel_list)
tunnel_list_frame.bind("<MouseWheel>", scroll_tunnel_list)
tunnel_list_frame.bind("<Button-4>", scroll_tunnel_list)
tunnel_list_frame.bind("<Button-5>", scroll_tunnel_list)

wind_sidebar = tk.LabelFrame(
    main_frame,
    text="Anemometer",
    font=("Arial", 14, "bold"),
    padx=12,
    pady=12
)
wind_sidebar.pack(side="right", fill="y", padx=(15, 0))

tk.Label(
    wind_sidebar,
    text="Windspeed",
    font=("Arial", 12),
    bg=COLORS["panel"]
).pack(anchor="w")
windspeed_label = tk.Label(
    wind_sidebar,
    text="N/A",
    font=("Arial", 18, "bold"),
    bg=COLORS["panel"]
)
windspeed_label.pack(anchor="w", pady=(8, 0))

detail_frame = tk.LabelFrame(
    main_frame,
    text="Tunnel details",
    font=("Arial", 14, "bold"),
    padx=24,
    pady=20
)
detail_frame.pack(side="left", fill="both", expand=True, padx=(15, 0))

detail_title = tk.Label(detail_frame, text="Select a tunnel", font=("Arial", 18, "bold"))
detail_title.pack(anchor="w", pady=(0, 15))

detail_widgets = {}

def select_tunnel(device_id):
    global selected_device_id
    selected_device_id = device_id
    tunnel = find_tunnel(device_id)
    if tunnel is None:
        return

    detail_title.config(text=f"{device_id} - {tunnel.get('role', '-')}")
    for key, value in detail_widgets["info"].items():
        value.config(text=get_tunnel_detail_value(tunnel, key))
    update_detail_status(tunnel)

def get_tunnel_detail_value(tunnel, key):
    thresholds = tunnel.get("thresholds", {})
    if key == "salinity_target":
        return (
            f'{thresholds.get("min_salinity", 0):g} - '
            f'{thresholds.get("salinity_target", 0):g} ppt'
        )
    if key == "water_level_target":
        return (
            f'{thresholds.get("min_level", 0):g} - '
            f'{thresholds.get("water_level_target", 0):g}'
        )
    return str(tunnel.get(key, "-"))

def update_detail_status(tunnel):
    enabled = tunnel["is_enabled"]
    detail_widgets["edit"].config(
        command=lambda d=tunnel["device_id"]: open_edit_tunnel_dialog(d)
    )
    detail_widgets["status"].config(text="Enabled" if enabled else "Disabled")
    detail_widgets["toggle"].config(
        text="Disable" if enabled else "Enable",
        command=lambda d=tunnel["device_id"]: toggle_tunnel_status(d)
    )
    detail_widgets["transfer"].config(
        text="TRANSFERRING"
        if tunnel["device_id"] in process_map
        else "Transfer: IDLE"
    )

def create_tunnel_view():
    for child in tunnel_list_frame.winfo_children():
        child.destroy()
    for child in detail_frame.winfo_children():
        if child != detail_title:
            child.destroy()
    tunnel_widgets.clear()
    detail_widgets.clear()

    for tunnel in TUNNELS:
        device_id = tunnel["device_id"]
        button = tk.Button(
            tunnel_list_frame,
            text=f'{device_id}\n{tunnel.get("role", "-")}',
            font=("Arial", 12),
            width=13,
            command=lambda d=device_id: select_tunnel(d)
        )
        button.pack(fill="x", pady=3)
        button.bind("<MouseWheel>", scroll_tunnel_list)
        button.bind("<Button-4>", scroll_tunnel_list)
        button.bind("<Button-5>", scroll_tunnel_list)

    status_label = tk.Label(detail_frame, text="-", font=("Arial", 14, "bold"))
    status_label.pack(anchor="w")
    transfer_label = tk.Label(detail_frame, text="Transfer: IDLE", font=("Arial", 11))
    transfer_label.pack(anchor="w", pady=(0, 15))

    info_frame = tk.Frame(detail_frame)
    info_frame.pack(fill="x")
    info_widgets = {}
    for key, name in [
        ("salinity_target", "Salinity target (ppt)"),
        ("water_level_target", "Water level target")
    ]:
        tk.Label(info_frame, text=name, font=("Arial", 12)).grid(
            row=len(info_widgets), column=0, sticky="w", pady=4
        )
        value_label = tk.Label(info_frame, text="-", font=("Arial", 12, "bold"))
        value_label.grid(row=len(info_widgets), column=1, sticky="w", padx=20, pady=4)
        info_widgets[key] = value_label

    sensor_frame = tk.LabelFrame(
        detail_frame, font=("Arial", 12, "bold"), padx=12, pady=8
    )
    sensor_frame.pack(fill="x", pady=(20, 0))
    sensor_labels = {}
    for sensor_index, (key, name) in enumerate([
        ("water_level", "Water Level"),
        ("salinity", "Salinity"),
        ("water_temperature", "Water Temp"),
        ("air_temperature", "Air Temp"),
        ("humidity", "Humidity"),
        ("ph", "pH")
    ]):
        tk.Label(sensor_frame, text=name, font=("Arial", 12)).grid(
            row=sensor_index, column=0, sticky="w", pady=3
        )
        value_label = tk.Label(sensor_frame, text="-", font=("Arial", 12, "bold"))
        value_label.grid(row=sensor_index, column=1, sticky="w", padx=20, pady=3)
        sensor_labels[key] = value_label

    action_frame = tk.Frame(detail_frame)
    action_frame.pack(fill="x", pady=(20, 0))
    edit_button = tk.Button(
        action_frame,
        text="Edit tunnel",
        font=("Arial", 12, "bold"),
        height=2
    )
    edit_button.grid(row=0, column=0, sticky="nsew")

    toggle_button = tk.Button(
        action_frame, text="-", font=("Arial", 13, "bold"), height=2
    )
    toggle_button.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
    action_frame.columnconfigure(0, weight=1, uniform="tunnel-actions")
    action_frame.columnconfigure(1, weight=1, uniform="tunnel-actions")
    detail_widgets.update({
        "status": status_label,
        "transfer": transfer_label,
        "edit": edit_button,
        "toggle": toggle_button,
        "info": info_widgets,
        "sensors": sensor_labels
    })

    if TUNNELS:
        device_id = selected_device_id if find_tunnel(selected_device_id) else TUNNELS[0]["device_id"]
        select_tunnel(device_id)
    else:
        detail_title.config(text="No tunnels configured")

def update_gui():
    if latest_windspeed is None:
        windspeed_label.config(text="N/A")
    else:
        windspeed_label.config(text=f"{latest_windspeed:.2f} m/s")

    for tunnel in TUNNELS:
        device_id = tunnel["device_id"]
        if device_id != selected_device_id or not detail_widgets:
            continue

        update_detail_status(tunnel)
        telemetry = latest_telemetry.get(device_id)
        if telemetry is None:
            for label in detail_widgets["sensors"].values():
                label.config(text="-")
        else:
            water_temperature = telemetry["water_temperature"]
            air_temperature = telemetry["air_temperature"]
            humidity = telemetry["humidity"]
            ph = telemetry["ph"]
            detail_widgets["sensors"]["water_level"].config(text=str(telemetry["water_level"]))
            detail_widgets["sensors"]["salinity"].config(
                text="N/A" if telemetry["salinity"] is None else f'{telemetry["salinity"]:.2f} ppt'
            )
            detail_widgets["sensors"]["water_temperature"].config(
                text="N/A" if water_temperature is None else f"{water_temperature:.2f} °C"
            )
            detail_widgets["sensors"]["air_temperature"].config(
                text="N/A" if air_temperature is None else f"{air_temperature:.2f} °C"
            )
            detail_widgets["sensors"]["humidity"].config(
                text="N/A" if humidity is None else f"{humidity:.2f} %"
            )
            detail_widgets["sensors"]["ph"].config(
                text="N/A" if ph is None else f"{ph:.2f}"
            )

    root.after(250, update_gui)




# CONFIGURATION


with open("config.json", "r", encoding="utf-8") as file:
    config = json.load(file)

CE_PIN = 22
CSN_PIN = 0
PAYLOAD_SIZE = 32

RASPI_ADDRESS = "RASPI".encode("ascii")
CHANNEL = 76
TUNNELS = config["tunnels"]

POLL_INTERVAL = 0.01
STATUS_INTERVAL = 5.0

# beri arduino waktu untuk menunggu sebelum mengirimkan paket berikutnya, untuk menghindari collision
TX_GUARD_DELAY = 0.05

# MESSAGE TYPES
MSG_REGISTER_REQUEST = 1
MSG_REGISTER_ACK = 2
MSG_TELEMETRY = 3
MSG_START_TRANSFER = 4
MSG_TRANSFER_COMPLETE = 5
MSG_SET_STATUS = 6



# REGISTRATION STATUS
STATUS_UNREGISTERED = 0
STATUS_DISABLED = 1
STATUS_ENABLED = 2


# QUEUES

incoming_queue = queue.Queue()
outgoing_queue = queue.Queue()

stop_event = threading.Event()

telemetry_stats = {} # statistik telemetry untuk setiap tunnel
process_map = {} # untuk menyimpan transfer yang sedang aktif untuk setiap tunnel

next_message_id = 1



# RADIO INITIALIZATION
radio = RF24(CE_PIN, CSN_PIN)

if not radio.begin():
    raise RuntimeError("nRF24 tidak terdeteksi.")

radio.setChannel(CHANNEL)
radio.setDataRate(RF24_250KBPS)
radio.setPALevel(RF24_PA_LOW)
radio.setPayloadSize(PAYLOAD_SIZE)
radio.setAutoAck(True)
radio.setRetries(5, 15)

radio.openReadingPipe(1, RASPI_ADDRESS)
radio.flush_rx()
radio.startListening()



# CONFIG LOOKUP

def find_tunnel(device_id):
    for tunnel in TUNNELS:
        if tunnel["device_id"] == device_id:
            return tunnel
    return None


def get_next_device_id():
    device_numbers = [
        int(match.group(1))
        for tunnel in TUNNELS
        if (match := re.fullmatch(r"A(\d{4})", tunnel["device_id"]))
    ]
    next_number = max(device_numbers, default=0) + 1

    if next_number > 9999:
        raise ValueError("No available tunnel IDs remain.")

    return f"A{next_number:04d}"



# MESSAGE ID

def get_next_message_id():
    global next_message_id
    message_id = next_message_id
    next_message_id += 1

    return message_id



# PACKET BUILDERS
def build_set_status(device_id, status):
    packet = struct.pack(
        "<B5sB",
        MSG_SET_STATUS,
        device_id.encode("ascii"),
        status
    )
    return packet.ljust(PAYLOAD_SIZE, b"\x00")

def build_register_ack(device_id, status):
    packet = struct.pack(
        "<B5sB",
        MSG_REGISTER_ACK,
        device_id.encode("ascii"),
        status
    )
    return packet.ljust(PAYLOAD_SIZE, b"\x00")


def build_start_transfer(device_id, message_id, min_level):
    min_level = int(round(min_level))

    if not 0 <= min_level <= 1023:
        raise ValueError("min_level harus berada dalam rentang ADC 0-1023")

    packet = struct.pack(
        "<B5sIH",
        MSG_START_TRANSFER,
        device_id.encode("ascii"),
        message_id,
        min_level
    )

    return packet.ljust(PAYLOAD_SIZE, b"\x00")


def save_config():
    with open("config.json", "w", encoding="utf-8") as file:
        json.dump(config, file, indent=2)

def open_edit_tunnel_dialog(device_id):
    tunnel = find_tunnel(device_id)
    if tunnel is None:
        return

    dialog = tk.Toplevel(root)
    dialog.title(f"Edit tunnel {device_id}")
    dialog.resizable(False, False)
    dialog.transient(root)
    dialog.grab_set()

    form = tk.Frame(dialog, padx=20, pady=15)
    form.pack()
    tk.Label(form, text="Role", font=("Arial", 11)).grid(
        row=0, column=0, sticky="w", padx=(0, 12), pady=6
    )
    role_combo = ttk.Combobox(
        form,
        values=ROLE_OPTIONS,
        state="readonly",
        width=20,
        font=("Arial", 11)
    )
    current_role = tunnel.get("role", "BACK").upper()
    role_combo.set(current_role if current_role in ROLE_OPTIONS else "BACK")
    role_combo.grid(row=0, column=1, pady=6)

    tk.Label(form, text="Salinity target (ppt)", font=("Arial", 11)).grid(
        row=1, column=0, sticky="w", padx=(0, 12), pady=6
    )
    thresholds = tunnel.setdefault("thresholds", {})
    min_salinity_entry = tk.Entry(form, width=10, font=("Arial", 11))
    min_salinity_entry.insert(0, str(thresholds.get("min_salinity", 0)))
    min_salinity_entry.grid(row=1, column=1, sticky="w", pady=6)
    salinity_target_entry = tk.Entry(form, width=10, font=("Arial", 11))
    salinity_target_entry.insert(0, str(thresholds.get("salinity_target", 0)))
    salinity_target_entry.grid(row=1, column=1, padx=(115, 0), pady=6)
    tk.Label(form, text="min                 max", font=("Arial", 8)).grid(
        row=2, column=1, sticky="w", padx=(2, 0)
    )
    tk.Label(form, text="Water level target", font=("Arial", 11)).grid(
        row=3, column=0, sticky="w", padx=(0, 12), pady=6
    )
    min_level_entry = tk.Entry(form, width=10, font=("Arial", 11))
    min_level_entry.insert(0, str(thresholds.get("min_level", 0)))
    min_level_entry.grid(row=3, column=1, sticky="w", pady=6)
    water_level_target_entry = tk.Entry(form, width=10, font=("Arial", 11))
    water_level_target_entry.insert(
        0, str(thresholds.get("water_level_target", 0))
    )
    water_level_target_entry.grid(row=3, column=1, padx=(115, 0), pady=6)
    tk.Label(form, text="min                 max", font=("Arial", 8)).grid(
        row=4, column=1, sticky="w", padx=(2, 0)
    )

    def save_changes():
        role = role_combo.get().strip().upper()
        min_salinity_text = min_salinity_entry.get().strip()
        salinity_target_text = salinity_target_entry.get().strip()
        min_level_text = min_level_entry.get().strip()
        water_level_target_text = water_level_target_entry.get().strip()

        try:
            min_salinity = float(min_salinity_text)
            salinity_target = float(salinity_target_text)
            min_level = float(min_level_text)
            water_level_target = float(water_level_target_text)
        except ValueError:
            messagebox.showerror(
                "Invalid target",
                "All target values must be numbers.",
                parent=dialog
            )
            return
        if (
            min_salinity < 0 or salinity_target < 0
            or min_level < 0 or water_level_target < 0
            or min_salinity > salinity_target
            or min_level > water_level_target
        ):
            messagebox.showerror(
                "Invalid target",
                "Targets must be non-negative and each min must not exceed its max.",
                parent=dialog
            )
            return

        tunnel["role"] = role
        thresholds["min_salinity"] = min_salinity
        thresholds["salinity_target"] = salinity_target
        thresholds["min_level"] = min_level
        thresholds["water_level_target"] = water_level_target
        save_config()
        create_tunnel_view()
        dialog.destroy()

    buttons = tk.Frame(form)
    buttons.grid(row=5, column=0, columnspan=2, pady=(12, 0))
    tk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="left", padx=5)
    tk.Button(buttons, text="Save", command=save_changes).pack(side="left", padx=5)
    role_combo.focus_set()

def open_add_tunnel_dialog():
    try:
        suggested_device_id = get_next_device_id()
    except ValueError as error:
        messagebox.showerror("Cannot add tunnel", str(error), parent=root)
        return

    dialog = tk.Toplevel(root)
    dialog.title("Add tunnel")
    dialog.resizable(False, False)
    dialog.transient(root)
    dialog.grab_set()

    form = tk.Frame(dialog, padx=20, pady=15)
    form.pack()
    entries = {}
    tk.Label(form, text="Device ID", font=("Arial", 11)).grid(
        row=0, column=0, sticky="w", padx=(0, 12), pady=6
    )
    device_id_entry = tk.Entry(form, width=22, font=("Arial", 11))
    device_id_entry.insert(0, suggested_device_id)
    device_id_entry.grid(row=0, column=1, pady=6)
    entries["device_id"] = device_id_entry

    tk.Label(form, text="Role", font=("Arial", 11)).grid(
        row=1, column=0, sticky="w", padx=(0, 12), pady=6
    )
    role_combo = ttk.Combobox(
        form,
        values=ROLE_OPTIONS,
        state="readonly",
        width=20,
        font=("Arial", 11)
    )
    role_combo.set("BACK")
    role_combo.grid(row=1, column=1, pady=6)
    entries["role"] = role_combo

    tk.Label(form, text="Salinity target (ppt)", font=("Arial", 11)).grid(
        row=2, column=0, sticky="w", padx=(0, 12), pady=6
    )
    min_salinity_entry = tk.Entry(form, width=10, font=("Arial", 11))
    min_salinity_entry.grid(row=2, column=1, sticky="w", pady=6)
    salinity_target_entry = tk.Entry(form, width=10, font=("Arial", 11))
    salinity_target_entry.grid(row=2, column=1, padx=(115, 0), pady=6)
    tk.Label(form, text="min                 max", font=("Arial", 8)).grid(
        row=3, column=1, sticky="w", padx=(2, 0)
    )

    tk.Label(form, text="Water level target", font=("Arial", 11)).grid(
        row=4, column=0, sticky="w", padx=(0, 12), pady=6
    )
    min_level_entry = tk.Entry(form, width=10, font=("Arial", 11))
    min_level_entry.grid(row=4, column=1, sticky="w", pady=6)
    water_level_target_entry = tk.Entry(form, width=10, font=("Arial", 11))
    water_level_target_entry.grid(row=4, column=1, padx=(115, 0), pady=6)
    tk.Label(form, text="min                 max", font=("Arial", 8)).grid(
        row=5, column=1, sticky="w", padx=(2, 0)
    )

    def add_tunnel():
        device_id = entries["device_id"].get().strip()
        role = entries["role"].get().strip().upper()
        values = (
            min_salinity_entry.get().strip(),
            salinity_target_entry.get().strip(),
            min_level_entry.get().strip(),
            water_level_target_entry.get().strip()
        )

        if not re.fullmatch(r"[A-Za-z0-9]{5}", device_id):
            messagebox.showerror(
                "Invalid device ID",
                "Device ID must contain exactly 5 letters or numbers.",
                parent=dialog
            )
            return
        if find_tunnel(device_id) is not None:
            messagebox.showerror(
                "Duplicate device ID",
                f"Tunnel {device_id} already exists.",
                parent=dialog
            )
            return
        try:
            min_salinity, salinity_target, min_level, water_level_target = (
                float(value) for value in values
            )
        except ValueError:
            messagebox.showerror(
                "Invalid target",
                "All target values must be numbers.",
                parent=dialog
            )
            return
        if (
            min_salinity < 0 or salinity_target < 0
            or min_level < 0 or water_level_target < 0
            or min_salinity > salinity_target
            or min_level > water_level_target
        ):
            messagebox.showerror(
                "Invalid target",
                "Targets must be non-negative and each min must not exceed its max.",
                parent=dialog
            )
            return

        TUNNELS.append({
            "device_id": device_id,
            "role": role,
            "is_enabled": False,
            "has_ph_meter": False,
            "thresholds": {
                "water_level_target": water_level_target,
                "min_level": min_level,
                "salinity_target": salinity_target,
                "min_salinity": min_salinity
            }
        })
        save_config()
        create_tunnel_view()
        dialog.destroy()

    buttons = tk.Frame(form)
    buttons.grid(row=6, column=0, columnspan=2, pady=(12, 0))
    tk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="left", padx=5)
    tk.Button(buttons, text="Add", command=add_tunnel).pack(side="left", padx=5)
    device_id_entry.focus_set()

def toggle_tunnel_status(device_id):
    tunnel = find_tunnel(device_id)
    if tunnel is None:
        return

    set_tunnel_status(
        device_id,
        not tunnel["is_enabled"]
    )

def set_tunnel_status(device_id, enabled):
    tunnel = find_tunnel(device_id)

    if tunnel is None:
        print(f"Tunnel {device_id} not found")
        return

    status = STATUS_ENABLED if enabled else STATUS_DISABLED
    status_name = "ENABLED" if enabled else "DISABLED"

    tunnel["is_enabled"] = enabled

    save_config()

    if not enabled:
        process_map.pop(device_id, None)

    outgoing_queue.put({
        "destination": device_id,
        "packet": build_set_status(device_id, status),
        "description": (
            f"SET_STATUS -> {device_id}, "
            f"status={status_name}"
        ),
        "send_at": time.monotonic() + TX_GUARD_DELAY
    })

    print(f"{device_id}: {status_name}")



# RADIO THREAD

def radio_worker():
    print("Radio Thread started.")

    pending_outgoing = None

    while not stop_event.is_set():

        # RECEIVE
        if radio.available():
            raw = bytes(radio.read(PAYLOAD_SIZE))

            if any(raw):
                incoming_queue.put(raw)

        # GET NEXT OUTGOING PACKET
        if pending_outgoing is None:
            try:
                pending_outgoing = outgoing_queue.get_nowait()
            except queue.Empty:
                pass


        # TRANSMIT AFTER GUARD DELAY
        if pending_outgoing:
            now = time.monotonic()

            if now >= pending_outgoing["send_at"]:
                destination = pending_outgoing["destination"]

                radio.stopListening(destination.encode("ascii"))
                
                packet = pending_outgoing["packet"]
                print("[TX RAW]", " ".join(f"{b:02X}" for b in packet[:12]))
                success = radio.write(packet)
                
                radio.startListening()

                if success:
                    print(f"[RADIO TX] {pending_outgoing['description']} [ACK]")
                else:
                    print(f"[RADIO TX] {pending_outgoing['description']} [FAILED]")

                outgoing_queue.task_done()
                pending_outgoing = None

        time.sleep(POLL_INTERVAL)

    radio.stopListening()

    print("Radio Thread stopped.")



# REGISTER REQUEST

def handle_register_request(raw):
    _, device_raw = struct.unpack("<B5s", raw[:6])

    device_id = device_raw.decode("ascii").rstrip("\x00")
    tunnel = find_tunnel(device_id)

    print()
    print(f"REGISTER_REQUEST <- {device_id}")

    if tunnel is None:
        status = STATUS_UNREGISTERED
        status_name = "UNREGISTERED"

    elif not tunnel["is_enabled"]:
        status = STATUS_DISABLED
        status_name = "DISABLED"

    else:
        status = STATUS_ENABLED
        status_name = "ENABLED"

    print(f"{device_id}: {status_name}")

    outgoing_queue.put({
        "destination": device_id,
        "packet": build_register_ack(device_id, status),
        "description": (f"REGISTER_ACK -> {device_id}, status={status_name}"),
        "send_at": time.monotonic() + TX_GUARD_DELAY
    })



# START TRANSFER

def request_start_transfer(device_id, min_level, message_id=None):
    if message_id is None:
        message_id = get_next_message_id()

    process_map[device_id] = message_id
    packet = build_start_transfer(device_id, message_id, min_level)
    print(f"build_start_transfer packet = {packet}")

    outgoing_queue.put({
        "destination": device_id,
        "packet": packet,
        "description": (
            f"START_TRANSFER -> {device_id}, "
            f"message_id={message_id}, "
            f"min_level={min_level}"
        ),
        "send_at": time.monotonic() + TX_GUARD_DELAY
    })

    print("\n*** START TRANSFER TRIGGERED ***")
    print(f"device={device_id}")
    print(f"message_id={message_id}")
    print(f"min_level={min_level}")



# TELEMETRY
def handle_telemetry(raw):
    (
        _,
        device_raw,
        sequence_id,
        water_temp_raw,
        air_temp_raw,
        humidity_raw,
        water_level_raw,
        salinity_raw,
        ph_raw
    ) = struct.unpack("<B5sIhhhHHh", raw[:22])

    device_id = device_raw.decode("ascii").rstrip("\x00")

    water_temperature = None if water_temp_raw == -1 else water_temp_raw / 100.0
    air_temperature = None if air_temp_raw == -1 else air_temp_raw / 100.0
    humidity = None if humidity_raw == -1 else humidity_raw / 100.0

    water_level = water_level_raw

    salinity_result = (
        konversi_salinitas(salinity_raw, water_temperature)
        if water_temperature is not None else None
    )

    salinity = salinity_result["ppt"] if salinity_result else None

    ph = adc_ke_ph(ph_raw) if ph_raw != -1 else None


    latest_telemetry[device_id] = {
        "water_temperature": water_temperature,
        "air_temperature": air_temperature,
        "humidity": humidity,
        "water_level": water_level,
        "salinity": salinity,
        "ph": ph
    }

    # LOGGING TO CONSOLE AND UPDATE TELEMETRY STATS
    if device_id not in telemetry_stats:
        telemetry_stats[device_id] = {
            "received": 0,
            "lost": 0,
            "duplicates": 0,
            "last_sequence": None
        }

    stats = telemetry_stats[device_id]
    last_sequence = stats["last_sequence"]

    if last_sequence is not None:
        if sequence_id == last_sequence:
            stats["duplicates"] += 1

        elif sequence_id > last_sequence + 1:
            stats["lost"] += sequence_id - last_sequence - 1

    stats["received"] += 1
    stats["last_sequence"] = sequence_id

    # PRINT TELEMETRY
    water_temp_text = "N/A" if water_temperature is None else f"{water_temperature:.2f}"
    air_temp_text = "N/A" if air_temperature is None else f"{air_temperature:.2f}"
    humidity_text = "N/A" if humidity is None else f"{humidity:.2f}"
    ph_text = "N/A" if ph is None else f"{ph:.2f}"
    water_level_text = "N/A" if water_level is None else f"{water_level}"
    salinity_text = "N/A" if salinity is None else f"{salinity:.2f}"


    print(
        f"TELEMETRY <- {device_id} "
        f"seq={sequence_id} | "
        f"water={water_temp_text}C | "
        f"air={air_temp_text}C | "
        f"humidity={humidity_text}% | "
        f"level={water_level_text} | "
        f"salinity={salinity_text} ppt | "
        f"pH={ph_text}"
    )

    # CHECK THRESHOLDS TO DETERMINE IF START_TRANSFER IS NEEDED
    tunnel = find_tunnel(device_id)

    if tunnel is None or not tunnel["is_enabled"]:
        return

    thresholds = tunnel["thresholds"]

    salinity_target = thresholds["salinity_target"]
    water_level_target = thresholds["water_level_target"]
    min_level = thresholds["min_level"]
    
    if device_id in process_map:
        request_start_transfer(device_id, min_level, process_map[device_id])
        return

    if (salinity is not None and water_level is not None and salinity >= salinity_target and water_level >= water_level_target):
        print(
            f"Threshold reached: "
            f"salinity {salinity_text} >= {salinity_target}, "
            f"water_level {water_level_text} >= {water_level_target}"
        )

        request_start_transfer(device_id, min_level)

def process_incoming_queue():
    try:
        raw = incoming_queue.get_nowait()
    except queue.Empty:
        raw = None

    if raw:
        message_type = raw[0]

        if message_type == MSG_REGISTER_REQUEST:
            handle_register_request(raw)

        elif message_type == MSG_TELEMETRY:
            handle_telemetry(raw)

        elif message_type == MSG_TRANSFER_COMPLETE:
            handle_transfer_complete(raw)

        else:
            print(f"Unknown message type: {message_type}")

        incoming_queue.task_done()

    root.after(10, process_incoming_queue)



# TRANSFER COMPLETE

def handle_transfer_complete(raw):
    _, device_raw, message_id = struct.unpack("<B5sI", raw[:10])

    device_id = device_raw.decode("ascii").rstrip("\x00")

    expected_message_id = process_map.get(device_id)

    if expected_message_id is None:
        print(
            f"TRANSFER_COMPLETE <- {device_id}, "
            f"message_id={message_id} "
            f"(no active transfer)"
        )
        return

    if message_id != expected_message_id:
        print(
            f"TRANSFER_COMPLETE <- {device_id}, "
            f"wrong message_id={message_id}, "
            f"expected={expected_message_id}"
        )
        return

    del process_map[device_id]

    print("\n(RX) TRANSFER COMPLETE RECEIVED")
    print(f"device={device_id}")
    print(f"message_id={message_id}")



# START RADIO THREAD

radio_thread = threading.Thread(
    target=radio_worker,
    name="RadioThread"
)

radio_thread.start()



# GUI CLOSE HANDLER
def on_close():
    stop_event.set()

    if radio_thread.is_alive():
        radio_thread.join()

    root.destroy()



# START GUI

create_tunnel_view()

process_incoming_queue()
update_gui()

root.protocol("WM_DELETE_WINDOW", on_close)

root.mainloop()
