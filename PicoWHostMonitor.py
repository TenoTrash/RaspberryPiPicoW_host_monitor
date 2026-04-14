import network
import asyncio
import socket
import time
from machine import Pin

# =========================
# Credenciales WiFi
# =========================

ssid = 'SSID WiFi'
password = 'PasswordWiFi'

# =========================
# Hosts a evaluar, IP y puertos disponibles para evaluar, porque el ICMP echo req me falla...
# =========================

HOSTS = [
    {"name": "Router", "host": "192.168.22.1", "ports": [80, 443]},
    {"name": "NAS", "host": "192.168.22.2", "ports": [22, 8080]},
    {"name": "Google DNS", "host": "8.8.8.8", "ports": [53]},
]

PING_INTERVAL = 60
TIMEOUT = 3
HISTORY_SIZE = 4

# =========================
# Pin del LED
# =========================

led = Pin("LED", Pin.OUT)

# =========================
# Apagamos el led...
# =========================

monitor_data = {}

for h in HOSTS:
    monitor_data[h["name"]] = {
        "history": ["-"] * HISTORY_SIZE,
        "last_ok": True,
        "latency": None
    }

# =========================
# Conectarse a la WiFi y dar IP y status por puerto serial
# =========================

def init_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(ssid, password)

    timeout = 10
    while timeout > 0:
        if wlan.status() >= 3:
            break
        timeout -= 1
        time.sleep(1)

    if wlan.status() != 3:
        print("WiFi FAIL")
        return False

    print("WiFi OK:", wlan.ifconfig()[0])
    return True

# =========================
# Ir chequeando cada uno de los hosts - probar con puertos porque no todos devuelven ICMP echo req
# =========================

def check_host(host, ports):
    start = time.ticks_ms()

    for port in ports:
        try:
            addr = socket.getaddrinfo(host, port)[0][-1]
            s = socket.socket()
            s.settimeout(TIMEOUT)
            s.connect(addr)
            s.close()

            latency = time.ticks_diff(time.ticks_ms(), start)
            return True, latency

        except:
            pass

    return False, None

# =========================
# El ping en si
# =========================

async def monitor_task():
    global monitor_data

    while True:
        for h in HOSTS:
            name = h["name"]
            ok, latency = check_host(h["host"], h["ports"])

            status = "OK" if ok else "FAIL"
            print(name, status, latency)

            data = monitor_data[name]

            data["history"].pop(0)
            if ok:
                data["history"].append(f"OK ({latency} ms)")
            else:
                data["history"].append("FAIL")

            data["last_ok"] = ok
            data["latency"] = latency

        await asyncio.sleep(PING_INTERVAL)

# =========================
# Alarma de led
# =========================

async def led_task():
    while True:
        any_fail = any(not d["last_ok"] for d in monitor_data.values())

        if any_fail:
            led.toggle()
            await asyncio.sleep(0.1)
        else:
            led.value(0)
            await asyncio.sleep(1)

# =========================
# HTML embebido, basado en la ayuda de RandomNerdTutorials
# =========================

def webpage():
    html_hosts = ""

    for name, data in monitor_data.items():
        status = "🟢 OK" if data["last_ok"] else "🔴 FAIL"

        history_html = "".join(f"<li>{h}</li>" for h in data["history"])

        latency = f"{data['latency']} ms" if data["latency"] else "-"

        html_hosts += f"""
        <h2>{name}</h2>
        <p>Estado: {status}</p>
        <p>Latencia: {latency}</p>
        <ul>{history_html}</ul>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Monitor de Red</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <meta http-equiv="refresh" content="5">
    </head>
    <body>
        <h1>Monitor de Red Pico W</h1>
        {html_hosts}
    </body>
    </html>
    """

    return html

# =========================
# JSON por las dudas
# =========================

def json_response():
    import ujson
    return ujson.dumps(monitor_data)

# =========================
# WEB SERVER
# =========================

async def handle_client(reader, writer):
    request_line = await reader.readline()

    try:
        request = request_line.decode().split()[1]
    except:
        request = "/"

    while await reader.readline() != b"\r\n":
        pass

    if request == "/json":
        response = json_response()
        writer.write("HTTP/1.0 200 OK\r\nContent-type: application/json\r\n\r\n")
        writer.write(response)
    else:
        response = webpage()
        writer.write("HTTP/1.0 200 OK\r\nContent-type: text/html; charset=utf-8\r\n\r\n")
        writer.write(response)

    await writer.drain()
    await writer.wait_closed()

# =========================
# MAIN
# =========================

async def main():
    if not init_wifi():
        return

    print("Starting server...")

    server = await asyncio.start_server(handle_client, "0.0.0.0", 80)

    asyncio.create_task(monitor_task())
    asyncio.create_task(led_task())

    while True:
        await asyncio.sleep(5)

# =========================
# RUN
# =========================

loop = asyncio.get_event_loop()
loop.create_task(main())
loop.run_forever()