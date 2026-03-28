# Evil Eye System GitHub Wiki 👁️

## 0. Room Layout (4 Walls + Central Tower) 🏰

The Evil Eye room is a square chamber with one "Wall" interactive surface on each of the four sides, and a massive **Execution Tower** in the very center.

### 📐 Physical Configuration

<details>
<summary><b>Click to View Room Schematic</b></summary>

```
          [   WALL 2   ]
          🔘 🔘 🔘 🔘 🔘
          🔘 🔘 👁️ 🔘 🔘
          🔘 🔘 🔘 🔘 🔘
               🔘
               
[ WALL 1 ]    [ 🏗️ ]    [ WALL 3 ]
🔘 🔘 🔘 🔘 🔘 [ T ] 🔘 🔘 🔘 🔘 🔘
🔘 🔘 👁️ 🔘 🔘 [ O ] 🔘 🔘 👁️ 🔘 🔘
🔘 🔘 🔘 🔘 🔘 [ R ] 🔘 🔘 🔘 🔘 🔘
     🔘                    🔘

          [   WALL 4   ]
          🔘 🔘 🔘 🔘 🔘
          🔘 🔘 👁️ 🔘 🔘
          🔘 🔘 🔘 🔘 🔘
               🔘
```

</details>

---


## 1. Verification Password (Checksum) 🔑

The system uses a custom lookup table over a 256-byte array. Calculate the sum of all bytes in your dynamic payload block (without the checksum itself). Compute bitwise AND 0xFF on the sum. Use this value as the index for PASSWORD_ARRAY and append that resulting byte to the absolute tail end of the packet before streaming.**Documentation Needed:** Depending on language, standard UDP socket libraries (sys/socket.h, System.Net.Sockets, java.net, socket) and multi-threading capabilities (pthread/std::thread, System.Threading, java.lang.Thread) are required.

<details>
<summary><b>Python Example</b></summary>

```python
password_array = [
    35, 63, 187, 69, 107, 178, 92, 76, 39, 69, 205, 37, 223, 255, 165, 231, 16, 220, 99, 61, 25, 203, 203, 155, 107, 30, 92, 144, 218, 194, 226, 88, 196, 190, 67, 195, 159, 185, 209, 24, 163, 65, 25, 172, 126, 63, 224, 61, 160, 80, 125, 91, 239, 144, 25, 141, 183, 204, 171, 188, 255, 162, 104, 225, 186, 91, 232, 3, 100, 208, 49, 211, 37, 192, 20, 99, 27, 92, 147, 152, 86, 177, 53, 153, 94, 177, 200, 33, 175, 195, 15, 228, 247, 18, 244, 150, 165, 229, 212, 96, 84, 200, 168, 191, 38, 112, 171, 116, 121, 186, 147, 203, 30, 118, 115, 159, 238, 139, 60, 57, 235, 213, 159, 198, 160, 50, 97, 201, 253, 242, 240, 77, 102, 12, 183, 235, 243, 247, 75, 90, 13, 236, 56, 133, 150, 128, 138, 190, 140, 13, 213, 18, 7, 117, 255, 45, 69, 214, 179, 50, 28, 66, 123, 239, 190, 73, 142, 218, 253, 5, 212, 174, 152, 75, 226, 226, 172, 78, 35, 93, 250, 238, 19, 32, 247, 223, 89, 123, 86, 138, 150, 146, 214, 192, 93, 152, 156, 211, 67, 51, 195, 165, 66, 10, 10, 31, 1, 198, 234, 135, 34, 128, 208, 200, 213, 169, 238, 74, 221, 208, 104, 170, 166, 36, 76, 177, 196, 3, 141, 167, 127, 56, 177, 203, 45, 107, 46, 82, 217, 139, 168, 45, 198, 6, 43, 11, 57, 88, 182, 84, 189, 29, 35, 143, 138, 171
]
def calc_checksum(data: bytes) -> int:
    idx = sum(data) & 0xFF
    return password_array[idx]
```

</details>

<details>
<summary><b>C# Example</b></summary>

```csharp
int[] password_array = {
    35, 63, 187, 69, 107, 178, 92, 76, 39, 69, 205, 37, 223, 255, 165, 231, 16, 220, 99, 61, 25, 203, 203, 155, 107, 30, 92, 144, 218, 194, 226, 88, 196, 190, 67, 195, 159, 185, 209, 24, 163, 65, 25, 172, 126, 63, 224, 61, 160, 80, 125, 91, 239, 144, 25, 141, 183, 204, 171, 188, 255, 162, 104, 225, 186, 91, 232, 3, 100, 208, 49, 211, 37, 192, 20, 99, 27, 92, 147, 152, 86, 177, 53, 153, 94, 177, 200, 33, 175, 195, 15, 228, 247, 18, 244, 150, 165, 229, 212, 96, 84, 200, 168, 191, 38, 112, 171, 116, 121, 186, 147, 203, 30, 118, 115, 159, 238, 139, 60, 57, 235, 213, 159, 198, 160, 50, 97, 201, 253, 242, 240, 77, 102, 12, 183, 235, 243, 247, 75, 90, 13, 236, 56, 133, 150, 128, 138, 190, 140, 13, 213, 18, 7, 117, 255, 45, 69, 214, 179, 50, 28, 66, 123, 239, 190, 73, 142, 218, 253, 5, 212, 174, 152, 75, 226, 226, 172, 78, 35, 93, 250, 238, 19, 32, 247, 223, 89, 123, 86, 138, 150, 146, 214, 192, 93, 152, 156, 211, 67, 51, 195, 165, 66, 10, 10, 31, 1, 198, 234, 135, 34, 128, 208, 200, 213, 169, 238, 74, 221, 208, 104, 170, 166, 36, 76, 177, 196, 3, 141, 167, 127, 56, 177, 203, 45, 107, 46, 82, 217, 139, 168, 45, 198, 6, 43, 11, 57, 88, 182, 84, 189, 29, 35, 143, 138, 171
};
public byte CalcChecksum(IEnumerable<byte> data) {
    return (byte)password_array[data.Sum(b => (int)b) & 0xFF];
}
```

</details>

<details>
<summary><b>C++ Example</b></summary>

```cpppp
const uint8_t password_array[256] = {
    35, 63, 187, 69, 107, 178, 92, 76, 39, 69, 205, 37, 223, 255, 165, 231, 16, 220, 99, 61, 25, 203, 203, 155, 107, 30, 92, 144, 218, 194, 226, 88, 196, 190, 67, 195, 159, 185, 209, 24, 163, 65, 25, 172, 126, 63, 224, 61, 160, 80, 125, 91, 239, 144, 25, 141, 183, 204, 171, 188, 255, 162, 104, 225, 186, 91, 232, 3, 100, 208, 49, 211, 37, 192, 20, 99, 27, 92, 147, 152, 86, 177, 53, 153, 94, 177, 200, 33, 175, 195, 15, 228, 247, 18, 244, 150, 165, 229, 212, 96, 84, 200, 168, 191, 38, 112, 171, 116, 121, 186, 147, 203, 30, 118, 115, 159, 238, 139, 60, 57, 235, 213, 159, 198, 160, 50, 97, 201, 253, 242, 240, 77, 102, 12, 183, 235, 243, 247, 75, 90, 13, 236, 56, 133, 150, 128, 138, 190, 140, 13, 213, 18, 7, 117, 255, 45, 69, 214, 179, 50, 28, 66, 123, 239, 190, 73, 142, 218, 253, 5, 212, 174, 152, 75, 226, 226, 172, 78, 35, 93, 250, 238, 19, 32, 247, 223, 89, 123, 86, 138, 150, 146, 214, 192, 93, 152, 156, 211, 67, 51, 195, 165, 66, 10, 10, 31, 1, 198, 234, 135, 34, 128, 208, 200, 213, 169, 238, 74, 221, 208, 104, 170, 166, 36, 76, 177, 196, 3, 141, 167, 127, 56, 177, 203, 45, 107, 46, 82, 217, 139, 168, 45, 198, 6, 43, 11, 57, 88, 182, 84, 189, 29, 35, 143, 138, 171
};
uint8_t calcChecksum(const std::vector<uint8_t>& data) {
    int sum = 0; for(auto b : data) sum += b;
    return password_array[sum & 0xFF];
}
```

</details>

<details>
<summary><b>Java Example</b></summary>

```java
final int[] passArray = {
    35, 63, 187, 69, 107, 178, 92, 76, 39, 69, 205, 37, 223, 255, 165, 231, 16, 220, 99, 61, 25, 203, 203, 155, 107, 30, 92, 144, 218, 194, 226, 88, 196, 190, 67, 195, 159, 185, 209, 24, 163, 65, 25, 172, 126, 63, 224, 61, 160, 80, 125, 91, 239, 144, 25, 141, 183, 204, 171, 188, 255, 162, 104, 225, 186, 91, 232, 3, 100, 208, 49, 211, 37, 192, 20, 99, 27, 92, 147, 152, 86, 177, 53, 153, 94, 177, 200, 33, 175, 195, 15, 228, 247, 18, 244, 150, 165, 229, 212, 96, 84, 200, 168, 191, 38, 112, 171, 116, 121, 186, 147, 203, 30, 118, 115, 159, 238, 139, 60, 57, 235, 213, 159, 198, 160, 50, 97, 201, 253, 242, 240, 77, 102, 12, 183, 235, 243, 247, 75, 90, 13, 236, 56, 133, 150, 128, 138, 190, 140, 13, 213, 18, 7, 117, 255, 45, 69, 214, 179, 50, 28, 66, 123, 239, 190, 73, 142, 218, 253, 5, 212, 174, 152, 75, 226, 226, 172, 78, 35, 93, 250, 238, 19, 32, 247, 223, 89, 123, 86, 138, 150, 146, 214, 192, 93, 152, 156, 211, 67, 51, 195, 165, 66, 10, 10, 31, 1, 198, 234, 135, 34, 128, 208, 200, 213, 169, 238, 74, 221, 208, 104, 170, 166, 36, 76, 177, 196, 3, 141, 167, 127, 56, 177, 203, 45, 107, 46, 82, 217, 139, 168, 45, 198, 6, 43, 11, 57, 88, 182, 84, 189, 29, 35, 143, 138, 171
};
public byte calcChecksum(byte[] data) {
    int sum = 0; for(byte b : data) sum += (b & 0xFF);
    return (byte) passArray[sum & 0xFF];
}
```

</details>

<details>
<summary><b>C Example</b></summary>

```c
const uint8_t password_array[256] = {
    35, 63, 187, 69, 107, 178, 92, 76, 39, 69, 205, 37, 223, 255, 165, 231, 16, 220, 99, 61, 25, 203, 203, 155, 107, 30, 92, 144, 218, 194, 226, 88, 196, 190, 67, 195, 159, 185, 209, 24, 163, 65, 25, 172, 126, 63, 224, 61, 160, 80, 125, 91, 239, 144, 25, 141, 183, 204, 171, 188, 255, 162, 104, 225, 186, 91, 232, 3, 100, 208, 49, 211, 37, 192, 20, 99, 27, 92, 147, 152, 86, 177, 53, 153, 94, 177, 200, 33, 175, 195, 15, 228, 247, 18, 244, 150, 165, 229, 212, 96, 84, 200, 168, 191, 38, 112, 171, 116, 121, 186, 147, 203, 30, 118, 115, 159, 238, 139, 60, 57, 235, 213, 159, 198, 160, 50, 97, 201, 253, 242, 240, 77, 102, 12, 183, 235, 243, 247, 75, 90, 13, 236, 56, 133, 150, 128, 138, 190, 140, 13, 213, 18, 7, 117, 255, 45, 69, 214, 179, 50, 28, 66, 123, 239, 190, 73, 142, 218, 253, 5, 212, 174, 152, 75, 226, 226, 172, 78, 35, 93, 250, 238, 19, 32, 247, 223, 89, 123, 86, 138, 150, 146, 214, 192, 93, 152, 156, 211, 67, 51, 195, 165, 66, 10, 10, 31, 1, 198, 234, 135, 34, 128, 208, 200, 213, 169, 238, 74, 221, 208, 104, 170, 166, 36, 76, 177, 196, 3, 141, 167, 127, 56, 177, 203, 45, 107, 46, 82, 217, 139, 168, 45, 198, 6, 43, 11, 57, 88, 182, 84, 189, 29, 35, 143, 138, 171
};
uint8_t calc_checksum(uint8_t* data, size_t len) {
    int sum = 0;
    for(size_t i=0; i<len; i++) sum += data[i];
    return password_array[sum & 0xFF];
}
```

</details>

## 2. Generating Packets 🧬

The Evil Eye topology maps an array of dictionaries representing 4 walls, 11 LEDs each. You must construct a strictly 132-byte frame layout. Each pixel requires 3 bytes spaced to accommodate hardware shift registers mathematically, iterating channel offset `channel - 1` alongside physical indexes.

<details>
<summary><b>Python Example</b></summary>

```python
def gen_frame(leds):
    frame = bytearray(132)
    for (ch, led), (r, g, b) in leds.items():
        idx = ch - 1
        frame[led * 12 + idx] = g
        frame[led * 12 + 4 + idx] = r
        frame[led * 12 + 8 + idx] = b
    return frame
```

</details>

<details>
<summary><b>C# Example</b></summary>

```csharp
public byte[] GenFrame(int ch, int led, byte r, byte g, byte b) {
    byte[] frame = new byte[132];
    int idx = ch - 1;
    frame[led * 12 + idx] = g;
    frame[led * 12 + 4 + idx] = r;
    frame[led * 12 + 8 + idx] = b;
    return frame;
}
```

</details>

<details>
<summary><b>C++ Example</b></summary>

```cpppp
std::vector<uint8_t> genFrame(int ch, int led, uint8_t r, uint8_t g, uint8_t b) {
    std::vector<uint8_t> frame(132, 0);
    int idx = ch - 1;
    frame[led * 12 + idx] = g;
    frame[led * 12 + 4 + idx] = r;
    frame[led * 12 + 8 + idx] = b;
    return frame;
}
```

</details>

<details>
<summary><b>Java Example</b></summary>

```java
public byte[] genFrame(int ch, int led, byte r, byte g, byte b) {
    byte[] frame = new byte[132];
    int idx = ch - 1;
    frame[led * 12 + idx] = g;
    frame[led * 12 + 4 + idx] = r;
    frame[led * 12 + 8 + idx] = b;
    return frame;
}
```

</details>

<details>
<summary><b>C Example</b></summary>

```c
void gen_frame(uint8_t* frame, int ch, int led, uint8_t r, uint8_t g, uint8_t b) {
    // Assumption: frame is pre-allocated strictly to 132 bytes via calloc
    int idx = ch - 1;
    frame[led * 12 + idx] = g;
    frame[led * 12 + 4 + idx] = r;
    frame[led * 12 + 8 + idx] = b;
}
```

</details>

## 3. Sending Network Frames 🚀

Streaming data to Port 4626 mandates precisely four sequenced datagram packets: (1) Start Frame 0x3344, (2) Layout Init 0xFFF0, (3) Frame Data 0x8877, (4) Execution 0x5566. **CRITICAL:** Hardware physically requires 8-millisecond mechanical buffering intervals. If 8ms sleep execution delays are bypassed, the network commands discard and screens freeze.

<details>
<summary><b>Python Example</b></summary>

```python
import socket, time
def send(ip, frame):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(build_start(), (ip, 4626))
    time.sleep(0.008) # 8ms block
    sock.sendto(build_init(), (ip, 4626))
    time.sleep(0.008)
    sock.sendto(build_data(frame), (ip, 4626))
    time.sleep(0.008)
    sock.sendto(build_end(), (ip, 4626))
```

</details>

<details>
<summary><b>C# Example</b></summary>

```csharp
using System.Net.Sockets; using System.Threading;
public void Send(string ip, byte[] frame) {
    using (UdpClient udp = new UdpClient()) {
        udp.Send(sPkt, sPkt.Length, ip, 4626); Thread.Sleep(8);
        udp.Send(iPkt, iPkt.Length, ip, 4626); Thread.Sleep(8);
        udp.Send(dPkt, dPkt.Length, ip, 4626); Thread.Sleep(8);
        udp.Send(ePkt, ePkt.Length, ip, 4626);
    }
}
```

</details>

<details>
<summary><b>C++ Example</b></summary>

```cpppp
#include <winsock2.h>
#include <thread>
void send(const char* ip) {
    SOCKET s = socket(AF_INET, SOCK_DGRAM, 0);
    sockaddr_in addr; addr.sin_family = AF_INET; addr.sin_port = htons(4626); addr.sin_addr.s_addr = inet_addr(ip);
    sendto(s, sPkt, sizeof(sPkt), 0, (sockaddr*)&addr, sizeof(addr));
    std::this_thread::sleep_for(std::chrono::milliseconds(8));
    // ... repeat
}
```

</details>

<details>
<summary><b>Java Example</b></summary>

```java
import java.net.*;
public void send(String ip) throws Exception {
    DatagramSocket s = new DatagramSocket();
    InetAddress addr = InetAddress.getByName(ip);
    s.send(new DatagramPacket(sPkt, sPkt.length, addr, 4626));
    Thread.sleep(8);
    // ... repeat
}
```

</details>

<details>
<summary><b>C Example</b></summary>

```c
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>
void send_data(const char* ip) {
    int s = socket(AF_INET, SOCK_DGRAM, 0);
    struct sockaddr_in addr; addr.sin_family = AF_INET; addr.sin_port = htons(4626); addr.sin_addr.s_addr = inet_addr(ip);
    sendto(s, sPkt, sizeof(sPkt), 0, (struct sockaddr*)&addr, sizeof(addr));
    usleep(8000); // 8000 microseconds = 8ms delay
    // ... repeat
}
```

</details>

## 4. Reading Button Data 👆

On port 7800, events map dynamically internally via UDP. Evil Eye payloads comprise exactly 687 bytes targeting offsets mapped statically into blocks of 171 channels. Evaluating hex block indicators identifies state: 0xCC (Trigger Pressed), 0x10 (Circuit Disconnected).

<details>
<summary><b>Python Example</b></summary>

```python
def listen():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 7800))
    while True:
        data, _ = sock.recvfrom(1024)
        if len(data) == 687 and data[0] == 0x88:
            for ch in range(1, 5):
                base = 2 + (ch - 1) * 171
                for led in range(11):
                    if data[base + 1 + led] == 0xCC: print(f"Wall {ch}, Button {led} PRESSED")
```

</details>

<details>
<summary><b>C# Example</b></summary>

```csharp
public void Listen() {
    using (UdpClient listener = new UdpClient(7800)) {
        IPEndPoint ep = new IPEndPoint(IPAddress.Any, 7800);
        while (true) {
            byte[] data = listener.Receive(ref ep);
            if (data.Length == 687 && data[0] == 0x88) {
                // Iteratively evaluate structural 171-offset block
            }
        }
    }
}
```

</details>

<details>
<summary><b>C++ Example</b></summary>

```cpppp
void listen() {
    SOCKET s = socket(AF_INET, SOCK_DGRAM, 0);
    sockaddr_in addr; addr.sin_family = AF_INET; addr.sin_port = htons(7800); addr.sin_addr.s_addr = INADDR_ANY;
    bind(s, (sockaddr*)&addr, sizeof(addr));
    char buf[1024];
    while(true) {
        int b = recvfrom(s, buf, sizeof(buf), 0, nullptr, nullptr);
        if(b == 687 && buf[0] == (char)0x88) { /* Decode state hex offsets */ }
    }
}
```

</details>

<details>
<summary><b>Java Example</b></summary>

```java
public void listen() throws Exception {
    DatagramSocket s = new DatagramSocket(7800);
    byte[] buf = new byte[1024];
    while (true) {
        DatagramPacket p = new DatagramPacket(buf, buf.length);
        s.receive(p);
        if (p.getLength() == 687 && buf[0] == (byte)0x88) { /* Decode */ }
    }
}
```

</details>

<details>
<summary><b>C Example</b></summary>

```c
void listen_triggers() {
    int s = socket(AF_INET, SOCK_DGRAM, 0);
    struct sockaddr_in addr; addr.sin_family = AF_INET; addr.sin_port = htons(7800); addr.sin_addr.s_addr = INADDR_ANY;
    bind(s, (struct sockaddr*)&addr, sizeof(addr));
    char buf[1024];
    while(1) {
        int bytes = recvfrom(s, buf, sizeof(buf), 0, NULL, NULL);
        if(bytes == 687 && buf[0] == (char)0x88) { /* Block iterator search for 0xCC */ }
    }
}
```

</details>

## 5. Hardware Behaviors & Timeouts ⏱️

**Timeout Behavior & Physical States:** Both configurations implicitly track an internal 3.0-second physical reset cycle loop limit timeout parameter directly hard-programmed onto PCB firmware chips.

**Sending Data:** To circumvent graphical dropout, visualizer endpoints must proactively and indefinitely fire continuous redundant UDP datagram sweeps toward `4626`.
**Receiving Triggers:** Since interaction event states mirror outbound buffer execution constraints mathematically via the 3-second cycle, physical devices remain inactive regarding hardware triggers (`0xCC / 7800 UDP`) whenever the corresponding controller instance freezes or otherwise stops transmitting outbound matrix packets entirely.

## 6. Multi-Threading Principles 🧵

**Crucial Setup Instructions:** Socket IO `recv()` functions aggressively block main code execution entirely. Similarly, the 8-millisecond delay cascades UI rendering performance if grouped on the main GUI framework instance. Thus, permanently running independent backend daemon threads for both Input (Listening) and Output (Sending) cycles simultaneously is categorically standard.

<details>
<summary><b>Python Example</b></summary>

```python
import threading

def run_system():
    # Sender isolates 4-packet synchronous blocks with internal .sleep() requirements
    threading.Thread(target=send_loop, daemon=True).start()
    
    # Receiver completely divorces port 7800 blocking UDP scrape
    threading.Thread(target=listen_loop, daemon=True).start()
    
    main_gui.mainloop() # Protected rendering thread runtime
```

</details>

<details>
<summary><b>C# Example</b></summary>

```csharp
using System.Threading.Tasks;

public void RunSystem() {
    // Utilize built in .NET scalable background thread pools
    Task.Run(() => SendLoop());
    Task.Run(() => ListenLoop());
    
    Application.Run(new MainWindow()); // Exists cleanly on isolated context
}
```

</details>

<details>
<summary><b>C++ Example</b></summary>

```cpppp
#include <thread>

void startSystem() {
    // Asynchronous thread initialization executing permanently
    std::thread senderWorker(sendLoop);
    std::thread receiverWorker(listenLoop);
    
    // Detach releases context execution completely maintaining background permanence
    senderWorker.detach();
    receiverWorker.detach();
    
    runGUI();
}
```

</details>

<details>
<summary><b>Java Example</b></summary>

```java
public void runSystem() {
    // Standard Java threaded runtime implementations
    new Thread(() -> sendLoop()).start();
    new Thread(() -> listenLoop()).start();
    
    launchJavaFXGUI();
}
```

</details>

<details>
<summary><b>C Example</b></summary>

```c
#include <pthread.h>

void start_system() {
    pthread_t send_thread, recv_thread;
    
    // Explicit low-level pthread assignments targeting void* casting functions
    pthread_create(&send_thread, NULL, send_loop, NULL);
    pthread_create(&recv_thread, NULL, listen_loop, NULL);
    
    // Non-blocking background detach states
    pthread_detach(send_thread);
    pthread_detach(recv_thread);
    
    start_gui_loop();
}
```

</details>

