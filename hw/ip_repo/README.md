# Vivado IP 의존성

- `bosio_output_core_1.0`: `VARZero/bosio_OutputCore` Git submodule
- `bosio_sensor_hub_mpu6050_1.0`: GY-521/MPU6050 직접 I²C 센서 허브 RTL
- `rgb2dvi`: Digilent HDMI 출력 IP, 사용자가 별도로 준비해야 함

저장소를 받을 때 `git clone --recursive`를 사용하거나 다음 명령으로 출력
코어 submodule을 초기화합니다.

```bash
git submodule update --init --recursive
```

`rgb2dvi`는 제3자 IP이므로 이 저장소에서 재배포하지 않습니다. Vivado가
`digilentinc.com:ip:rgb2dvi:1.4`를 찾을 수 있도록 이 디렉터리에 IP 저장소를
추가하십시오.
