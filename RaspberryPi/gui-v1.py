import json
import queue
import struct
import threading
import time
import tkinter as tk

from pyrf24 import RF24, RF24_250KBPS, RF24_PA_LOW


latest_telemetry = {}
tunnel_widgets = {}

root = tk.Tk()
root.title("Smart Salt Tunnel")
root.geometry("1024x600")

scroll_container = tk.Frame(root)
scroll_container.pack(
    fill="both",
    expand=True,
    padx=20,
    pady=10
)

canvas = tk.Canvas(
    scroll_container,
    highlightthickness=0
)

scrollbar = tk.Scrollbar(
    scroll_container,
    orient="vertical",
    command=canvas.yview,
    width=35
)

canvas.configure(
    yscrollcommand=scrollbar.set
)

scrollbar.pack(
    side="right",
    fill="y"
)

canvas.pack(
    side="left",
    fill="both",
    expand=True
)

tunnel_frame = tk.Frame(canvas)

tunnel_window = canvas.create_window(
    (0, 0),
    window=tunnel_frame,
    anchor="nw"
)

def update_scroll_region(event):
    canvas.configure(
        scrollregion=canvas.bbox("all")
    )

def resize_tunnel_frame(event):
    canvas.itemconfigure(
        tunnel_window,
        width=event.width
    )

tunnel_frame.bind(
    "<Configure>",
    update_scroll_region
)

canvas.bind(
    "<Configure>",
    resize_tunnel_frame
)

def create_tunnel_cards():
    for index, tunnel in enumerate(TUNNELS):
        device_id = tunnel["device_id"]
        role = tunnel["role"]

        row = index // 3
        column = index % 3

        card = tk.LabelFrame(
            tunnel_frame,
            text=f"{device_id} - {role}",
            font=("Arial", 16, "bold"),
            padx=18,
            pady=15
        )

        card.grid(
            row=row,
            column=column,
            padx=10,
            pady=10,
            sticky="nsew"
        )

        # STATUS
        status_label = tk.Label(
            card,
            text="-",
            font=("Arial", 14, "bold")
        )

        status_label.grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(0, 3)
        )

        transfer_label = tk.Label(
            card,
            text="Transfer: IDLE",
            font=("Arial", 11)
        )

        transfer_label.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(0, 12)
        )

        # SENSOR VALUES
        sensor_names = [
            ("water_level", "Water Level"),
            ("salinity", "Salinity"),
            ("water_temperature", "Water Temp"),
            ("air_temperature", "Air Temp"),
            ("humidity", "Humidity"),
            ("ph", "pH")
        ]

        sensor_labels = {}

        for sensor_index, (key, name) in enumerate(sensor_names):
            label = tk.Label(
                card,
                text=name,
                font=("Arial", 12)
            )

            label.grid(
                row=sensor_index + 2,
                column=0,
                sticky="w",
                pady=3
            )

            value_label = tk.Label(
                card,
                text="-",
                font=("Arial", 12, "bold")
            )

            value_label.grid(
                row=sensor_index + 2,
                column=1,
                sticky="e",
                pady=3
            )

            sensor_labels[key] = value_label

        toggle_button = tk.Button(
            card,
            text="-",
            font=("Arial", 13, "bold"),
            height=2,
            command=lambda d=device_id: toggle_tunnel_status(d)
        )

        toggle_button.grid(
            row=8,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(15, 0)
        )

        card.columnconfigure(0, weight=1)
        card.columnconfigure(1, weight=1)

        tunnel_widgets[device_id] = {
            "status": status_label,
            "transfer": transfer_label,
            "toggle": toggle_button,
            "sensors": sensor_labels
        }

    for column in range(3):
        tunnel_frame.columnconfigure(
            column,
            weight=1,
            uniform="tunnel_columns"
        )

    for row in range((len(TUNNELS) + 2) // 3):
        tunnel_frame.rowconfigure(row, weight=1)

def update_gui():
    for tunnel in TUNNELS:
        device_id = tunnel["device_id"]

        widgets = tunnel_widgets.get(device_id)

        if widgets is None:
            continue

        # STATUS
        if tunnel["is_enabled"]:
            widgets["status"].config(
                text="ENABLED"
            )

            widgets["toggle"].config(
                text="DISABLE"
            )

        else:
            widgets["status"].config(
                text="DISABLED"
            )

            widgets["toggle"].config(
                text="ENABLE"
            )

        # TRANSFER
        if device_id in process_map:
            message_id = process_map[device_id]

            widgets["transfer"].config(
                text=f"TRANSFERRING"
            )

        else:
            widgets["transfer"].config(
                text="IDLE"
            )

        # TELEMETRY
        telemetry = latest_telemetry.get(device_id)

        if telemetry is None:
            for label in widgets["sensors"].values():
                label.config(text="-")

        else:
            water_temperature = telemetry["water_temperature"]
            air_temperature = telemetry["air_temperature"]
            humidity = telemetry["humidity"]
            ph = telemetry["ph"]

            widgets["sensors"]["water_level"].config(
                text=str(telemetry["water_level"])
            )

            widgets["sensors"]["salinity"].config(
                text=f'{telemetry["salinity"]:.2f} ppt'
            )

            widgets["sensors"]["water_temperature"].config(
                text="N/A"
                if water_temperature is None
                else f"{water_temperature:.2f} °C"
            )

            widgets["sensors"]["air_temperature"].config(
                text="N/A"
                if air_temperature is None
                else f"{air_temperature:.2f} °C"
            )

            widgets["sensors"]["humidity"].config(
                text="N/A"
                if humidity is None
                else f"{humidity:.2f} %"
            )

            widgets["sensors"]["ph"].config(
                text="N/A"
                if ph is None
                else f"{ph:.2f}"
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
    salinity = salinity_raw / 100.0

    ph = None if ph_raw == -1 else ph_raw / 100.0


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


    print(
        f"TELEMETRY <- {device_id} "
        f"seq={sequence_id} | "
        f"water={water_temp_text}C | "
        f"air={air_temp_text}C | "
        f"humidity={humidity_text}% | "
        f"level={water_level} | "
        f"salinity={salinity:.2f} | "
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

    if (salinity >= salinity_target and water_level >= water_level_target):
        print(
            f"Threshold reached: "
            f"salinity {salinity:.2f} >= {salinity_target}, "
            f"water_level {water_level} >= {water_level_target}"
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

create_tunnel_cards()

process_incoming_queue()
update_gui()

root.protocol("WM_DELETE_WINDOW", on_close)

root.mainloop()
