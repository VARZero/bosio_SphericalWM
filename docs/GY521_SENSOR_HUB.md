# GY-521 직접 RTL 센서 허브

## 현재 데이터 경로

GY-521의 MPU6050은 PYNQ-Z2의 Pmod B에 연결된다. 센서 초기화, I2C 읽기,
자이로 영점 보정, 자세 추정과 AXI4-Stream 전송을 모두 PL의
`bosio_sensor_hub_mpu6050` IP가 처리한다.

```text
GY-521 / MPU6050
       │ I2C, Pmod B
       ▼
bosio_sensor_hub_mpu6050 (RTL)
  ├─ MPU6050 초기화와 14바이트 burst read
  ├─ 256샘플 자이로 영점 보정
  ├─ 고정소수점 complementary filter
  └─ {roll, pitch, yaw}, signed 32-bit mrad
       │ AXI4-Stream 96-bit
       ▼
bosio_output_core/s_axis_sensor
       │ 센서 자세 → Q24 투영 계수 생성
       ▼
정이십면체 프레임버퍼 투영기 → HDMI
```

실시간 센서 경로에는 ARM, Python, AXI IIC가 개입하지 않는다. Python
드라이버는 비트스트림과 장면을 올리고 출력 코어의 센서 모드를 켜는 역할만
한다. `sw/bosio_gy521.py`와 `sw/run_gy521_hub.py`는 예전 AXI-IIC overlay를
진단할 때 쓰는 소프트웨어 대체 경로로만 보존한다.

## 배선

보드와 GY-521 전원을 끈 상태에서 연결한다.

| GY-521 | PYNQ-Z2 Pmod B | FPGA 핀 | 설명 |
|---|---|---|---|
| `VCC` | `3V3` | - | 3.3 V 전원 |
| `GND` | `GND` | - | 공통 접지 |
| `SDA` | 물리 핀 3 (`pmodb_gpio[2]`, JB2_P) | `T11` | I2C 데이터 |
| `SCL` | 물리 핀 4 (`pmodb_gpio[3]`, JB2_N) | `T10` | I2C 클록 |
| `AD0` | GND 또는 미연결 | - | 주소 `0x68` 선택 |
| `INT` | 미연결 | - | 현재 폴링 방식에서 미사용 |

Pmod의 실크 인쇄와 GY-521의 핀 이름을 직접 확인한다. XDC는 SDA/SCL을
LVCMOS33 양방향 오픈드레인 신호로 배치하며 각각 IOBUF 하나를 사용한다.
내부 PULLUP도 설정했으며, 일반적인 GY-521 보드의 외부 풀업과 함께 동작한다.

## RTL 동작

전원이 안정된 뒤 다음 레지스터를 순서대로 기록한다.

| 레지스터 | 값 | 의미 |
|---|---:|---|
| `PWR_MGMT_1` (`0x6B`) | `0x01` | 슬립 해제, X gyro 기준 클록 |
| `CONFIG` (`0x1A`) | `0x03` | DLPF 설정 |
| `GYRO_CONFIG` (`0x1B`) | `0x08` | ±500 °/s |
| `ACCEL_CONFIG` (`0x1C`) | `0x08` | ±4 g |
| `SMPLRT_DIV` (`0x19`) | `0x09` | 내부 100 Hz 샘플링 |

허브는 `ACCEL_XOUT_H` (`0x3B`)부터 14바이트를 반복 START로 한 번에 읽는다.
읽기 시간을 포함한 read-to-read 주기는 약 10 ms이다. NACK 또는 짧은 읽기가
발생하면 오류 상태를 기록하고 다음 주기에 다시 읽는다. 초기화 중 NACK가
발생하면 전원 안정화 단계부터 재시도한다.

처음 256개 정상 샘플로 X/Y/Z 자이로 평균을 구한다. 약 2.7초 동안 센서를
평평하게 고정해야 한다. 이후 pitch와 roll은 자이로 적분값 63/64와 중력
기준값 1/64를 결합한다. yaw는 Z축 자이로 적분이며 ±3142 mrad 범위로
wrap한다.

MPU6050에는 지자기 센서가 없으므로 yaw는 시간이 지나면 드리프트한다.
현재 중력 기반 pitch/roll 계산은 수평 부근의 선형 근사이므로 큰 기울기에서
오차가 증가한다. 실제 장착 방향에 따른 축 교환과 부호 보정은 센서 도착 후
측정해 확정한다.

## AXI4-Stream 형식

한 샘플은 96비트이며 모든 각도는 signed 32-bit 2의 보수 mrad이다.

| 비트 | 값 |
|---|---|
| `[31:0]` | yaw |
| `[63:32]` | pitch |
| `[95:64]` | roll |

`tvalid`는 출력 코어가 `tready`로 수락할 때까지 유지된다. 출력 코어는 이
원시 yaw/pitch/roll을 받아 내부 `sensor_pose` 엔진에서 정이십면체 투영용
Q24 계수 180개를 생성하고 프레임 경계에서 적용한다. Q24 값 자체가 센서
허브에서 전송되는 것은 아니다.

## 빌드와 실행

Vivado 2020.2에서 다음 순서로 IP를 다시 패키징하고 전체 bitstream을 만든다.

```powershell
& D:\Xilinx2020\Vivado\2020.2\bin\vivado.bat -mode batch `
  -source hw/scripts/package_mpu6050_sensor_hub_ip.tcl
& D:\Xilinx2020\Vivado\2020.2\bin\vivado.bat -mode batch `
  -source hw/scripts/build_output_bitstream.tcl
```

생성물은 `sw/bitstream/bosio_output_disp.bit`와 같은 이름의 `.hwh`이다.
센서를 연결한 뒤 PYNQ에서 실행한다.

```bash
cd /home/xilinx/bosio_v2
sudo /usr/local/share/pynq-venv/bin/python3 run_gy521_direct.py \
  --bit bitstream/bosio_output_disp.bit --scene scene_v2.npy
```

`run_gy521_direct.py`는 장면을 올리고 `BosioV2.use_sensor(True)`를 호출한 뒤
수신 패킷 수와 원시 자세를 주기적으로 표시한다.

### 축 방향 반전 레지스터

출력 코어의 AXI-Lite `0x20` 레지스터는 센서 자세가 Q24 투영 계수로
변환되기 전에 각 축의 방향을 독립적으로 반전한다.

| 비트 | 값 1의 의미 |
|---:|---|
| 0 | yaw 반전 |
| 1 | pitch 반전 |
| 2 | roll 반전 |

```python
driver.set_sensor_invert(yaw=True, pitch=False, roll=True)
```

실행 명령에서도 설정할 수 있다.

```bash
python3 run_gy521_direct.py --invert-yaw --invert-roll
```

레지스터의 기본값은 `0`이며 다음 센서 패킷부터 적용된다. 원시 센서 상태
레지스터 `0x24`~`0x2C`는 진단을 위해 반전 전 값을 계속 표시한다.

## 센서 도착 후 시험 순서

1. 보드 전원을 끄고 3.3 V, GND, SDA(T11), SCL(T10), AD0(GND)를 확인한다.
2. 새 `.bit`와 `.hwh`를 보드에 복사하고 `run_gy521_direct.py`를 실행한다.
3. 보정 안내 후 약 3초 동안 센서를 평평하게 고정한다.
4. `sensor_active=true`이고 `sensor_packets`가 계속 증가하는지 확인한다.
5. 정지 상태에서 pitch/roll이 0 부근인지 확인한다.
6. X, Y, Z축을 하나씩 움직여 화면 방향, 축 순서와 부호를 기록한다.
7. 10분 정지 시험으로 yaw drift와 pitch/roll 흔들림을 측정한다.
8. 창 여러 개를 띄운 장면에서 프레임 경계 갱신과 이동 부드러움을 확인한다.

실물 GY-521 시험에서는 초기화, 연속 샘플 수신, 약 100 Hz 패킷 생성,
출력 코어 적용과 HDMI 화면 회전을 확인했다. 케이스 장착 방향은 `0x20`
축 반전 레지스터와 드라이버 옵션으로 보정할 수 있다.

## 사전 구현 검증 결과

2026-09-12에 Vivado 2020.2로 최종 RTL을 PYNQ-Z2용으로 합성하고
배치·배선한 뒤 bitstream을 생성했다.

| 항목 | 결과 |
|---|---:|
| 구현/DRC 오류 | 0 |
| setup WNS | +0.137 ns |
| hold WHS | +0.050 ns |
| Slice LUT | 25,452 / 53,200 (47.84%) |
| Slice Register | 23,773 / 106,400 (22.34%) |
| Block RAM Tile | 137.5 / 140 (98.21%) |
| DSP | 83 / 220 (37.73%) |
| SCL | T10, BIDIR, LVCMOS33, PULLUP |
| SDA | T11, BIDIR, LVCMOS33, PULLUP |

HWH에는 `sensor_hub_0/m_axis_sensor`와
`output_core_0/s_axis_sensor`의 TDATA/TVALID/TREADY 직접 연결이 기록되어
있다. SCL/SDA에는 각각 IOBUF가 합성됐으며 AXI IIC 인스턴스는 없다.

### PYNQ-Z2 실물 연결 결과

2026-09-12에 GY-521을 Pmod B에 연결해 최종 overlay를 실행했다. 재보정 후
약 9초 동안 `sensor_packets`가 1에서 907로, `sensor_applied`가 1에서
904로 증가했다. 측정 수신률은 약 100.67 Hz였고 `sensor_active=true`,
출력 코어 오류는 없었다. 정지 측정에서 yaw는 0에서 1 mrad, roll은
-7 mrad로 안정적이었다.

현재 연결 자세에서는 pitch가 약 -1035 mrad로 측정되어 장면 시야 밖을
가리켰다. 캡처보드는 1280×720 60 Hz HDMI 신호를 정상 수신했지만 화면
내용은 검게 나타났다. GY-521의 Z축이 중력 방향과 나란하도록 평평하게
놓은 뒤 화면 이동 방향을 다시 확인해야 한다. 원시 결과는
`verification/gy521_board_validation.json`에 기록했다.

## 구현 파일

- `hw/ip_repo/bosio_sensor_hub_mpu6050_1.0/hdl/bosio_i2c_reg_master.v`
- `hw/ip_repo/bosio_sensor_hub_mpu6050_1.0/hdl/bosio_sensor_hub_mpu6050.v`
- `hw/scripts/package_mpu6050_sensor_hub_ip.tcl`
- `hw/scripts/create_output_system.tcl`
- `hw/constrs/pynq_z2_hdmi.xdc`
- `sw/run_gy521_direct.py`
- `sw/bosio_driver_v2.py`
