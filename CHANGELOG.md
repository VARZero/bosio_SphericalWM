# 변경 기록

## 1.2.0 - 2026-09-14

- BS24 출력 코어에 1픽셀/클록 경계 적응형 투영 안티에일리어싱 추가
- AA enable, 밝기 임계값, 혼합 강도를 드라이버와 IPC에서 런타임 설정
- 1280×24비트 줄 버퍼를 분산 RAM으로 배치하고 연산을 4단으로 파이프라인화
- 완성된 BOSIO 장면 패킷을 독점 전송하는 `scene-stream` IPC 추가
- 출력 코어 RTL 시뮬레이션과 PYNQ-Z2 통합 bitstream 갱신

## 1.1.0 - 2026-09-13

- BTN0..BTN3 독립 AXI GPIO, Linux 직접 판독 및 디바운스된 데몬 이벤트 API 추가

## 1.0.0 - 2026-09-13

- 구면 좌표 창, 포커스, z-order와 구면 마우스 IPC 구현
- C++17/ARM NEON 직접 RGB332 합성 및 장면 패킹 구현
- dirty rectangle 기반 셀 재합성과 BPT1 부분 타일 DMA 구현
- BS23 출력 코어의 양쪽 BRAM bank 부분 갱신 지원
- GY-521 센서 허브 자세 스트림 연동
- PYNQ `bootpy.service` 이후 bitstream과 데몬을 자동 기동하는 systemd 설치 지원
- PYNQ-Z2 실물 HDMI 및 60 Hz 국소 갱신 벤치마크 완료
