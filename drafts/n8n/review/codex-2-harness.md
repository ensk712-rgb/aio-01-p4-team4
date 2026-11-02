# Codex 2차 · 독립 검증 환경 인계

2026-11-02. Claude 1차 설계 및 끝의 대조 결과를 읽고, 구현 코드에 의존하지 않는 시험 환경을 만들었다. 작업 파일은 `drafts/n8n/verify/`에만 작성했다. 이 문서는 브리프가 별도로 지정한 인계 산출물이다. 원본 `cases/`, `lib/`, 과정 키트, 기존 컨테이너 및 aio-t4를 변경하지 않았고 git 명령과 실제 API 키 조회도 하지 않았다.

## 준비된 파일

| 파일 | 역할 |
| --- | --- |
| `verify/compose.yml` | project `ticketmoa-verify`, 전용 internal 네트워크와 n8n named volume. n8n 2.42.6은 5699, 읽기 전용 77 API는 8899, mock은 8898. 호스트 포트는 127.0.0.1에만 바인딩 |
| `verify/prepare-data.sh` | 과정 77 data 복사 후 팀 employees/tickets/docs로 교체. docs는 기존 문서를 제거한 뒤 팀 Markdown 8개만 배치. 원본 날짜 보존 |
| `verify/mock_openai.py` | 표준 라이브러리 HTTP mock, triage/writer/verifier 표지, 6개 장애 모드, 모델/임베딩/통계, 채팅 SSE 지원 |
| `verify/credentials.json.example` | 지정된 ID/이름의 Credential 세 개. 전부 공개 시험용 가짜 값 |
| `verify/register-credentials.sh` | 이 Compose 프로젝트의 n8n에만 Credential import |
| `verify/up.sh` | 워크플로우 10개/ID 사전 검사 → 준비 → 기동 → Credential import → errors 먼저/support 마지막 import·publish → n8n restart → 준비 대기 → 색인 전 검사 → 색인·검색 확인 |
| `verify/down.sh` | 이 프로젝트에만 compose down --volumes --remove-orphans. 전역 prune 없음 |
| `verify/runner.py` | 원본 판정 + 독립 엄격 검사, 인증 헤더, before/after 변환, 동일 요청 repeat, JSON 보고서 |
| `verify/adversarial.json` | 문서 근거를 먼저 적은 반례 19개 그룹(33개 단계). 그룹 내부는 순서/상태 유지, 그룹 사이 초기화 |
| `verify/test_harness.py` | mock의 실제 로컬 HTTP 동작 및 판정기/엄격 검사의 단위 검증 |
| `verify/reports/unit-tests.txt` | 직접 실행한 단위 검증 결과 |

상대 경로는 Compose 파일 위치 기준이다. 데이터 API 소스 마운트는 요청한 `../../../../aio-01d4-stu/Last3Mon/77/data-api/server.py`이고 수정 없이 실행한다. runtime-data는 재생성 가능한 읽기 전용 bind mount, n8n DB는 전용 named volume이다. API의 cache/ticket/DLQ/log/alert 상태는 원본 API처럼 메모리에 있으므로 API 재시작으로 사라진다. down은 n8n volume을 지우지만 호스트의 runtime-data와 reports는 보존한다.

## 사용법

저장소 루트에서:

```bash
cd drafts/n8n/verify
./up.sh
python3 -B runner.py --suite common --repeat 1
python3 -B runner.py --suite team --repeat 1
python3 -B runner.py --suite adversarial
python3 -B runner.py --suite all --repeat 3
./down.sh
```

워크플로우 JSON은 `drafts/n8n/workflows/ticketmoa-{support,agents,refund,index,search,tech,payment,handoff,errors,ops}.json` 열 개가 있어야 한다. 생성기를 자동 실행하거나 워크플로우를 수정하지 않는다. JSON의 ID가 없거나 중복되면 up은 컨테이너를 만들기 전에 중단한다. Credential ID는 제공한 가짜 Credential과 일치해야 하고, LLM base URL은 mock으로 향해야 한다. 실행기는 실제 OpenAI로 접속하지 않으며 전용 internal 네트워크도 외부 접속을 제한한다.

```bash
# Docker 없이 mock과 러너 자체 검증
python3 -B -m unittest -v test_harness

# 필요할 때 개별 단계
./prepare-data.sh
python3 -B runner.py --wait-ready
python3 -B runner.py --pre-index   # 반드시 새 n8n 프로세스에서 index 전에
python3 -B runner.py --index
```

색인 전 측정은 up에서 자동 실행하며 별도 `reports/pre-index-*.json`을 남긴다. 이후에는 색인돼 있으므로 같은 프로세스에 --pre-index를 재실행해 통과할 것으로 기대하면 안 된다. 실제 준비 상태가 `indexed:false`인지 보고, 색인 이후에는 QR 검색에 hits가 생기는지도 확인한다. errors는 Error Trigger이므로 인증 없는 하위 webhook 검사 대상에서 제외했다.

러너의 --suite는 시작할 때 **이 격리 API의** fault/cache/tickets/DLQ/alerts/live logs를 초기화한다. suite 내부에서는 원본 before/after를 실행하고 TM-02→03 상태를 보존한다. all에서는 common/team 각각을 초기화하고, 반례는 그룹별로 초기화한다. TM-09에만 동일 질문·새 request_id를 실제로 다섯 번 보내 준비한다. 주석 context.note를 상태로 신뢰하지 않는다. localhost:8800 hook은 127.0.0.1:8899로 바꾸고, llm down/up은 mock state만 바꾼다. URL 허용 목록으로 기존 과정 포트/서버를 호출하지 못하게 했다.

## 판정과 보고서 해석

`field`, `as_text`, `judge`는 77일차 flow.py에서 그대로 복사했다(range 포함). AST 동일성 검증도 통과했다. 원본의 contains any-of와 null ticket 거짓 양성을 그대로 재현하고, 이를 `strict_errors`에서 별도로 잡는다. 원본 케이스 파일은 수정하지 않았다.

엄격 검사는 다음을 포함한다.

- 공통 응답 10개 필드의 존재·타입, request_id, route enum, 출처 doc/section/유한 score, ticket.id, agents.llm_calls, security 및 timings 형식. 브리프의 “9칸”은 AGENTS 계약상 실제 10칸이므로 10개로 구현했다.
- 요구된 이관 케이스의 ticket.id 및 `/tickets-created`의 실제 key/id 연결. WF-09는 key=wf09인 생성 건수 1과 동일 id를 검사한다.
- WF-04의 케이스 전체 DLQ 증가 1·알림 증가 1, WF-12의 두 문구(현장 발권 **및** 접수)·high·알림 증가 1. repeat의 재생이 부작용을 중복하면 실패한다.
- WF-08의 채팅/임베딩 mock 호출 증가 모두 0.
- 응답 및 API의 live logs/alerts/DLQ/tickets-created에서 팀 fixture 연락처 원문이 발견되면 실패. 과정 seed log는 팀 요청 결과가 아니므로 live만 조회한다.
- TM-02의 152,000원 및 수수료 0원 표시. 미래 예매일인 C-2005를 수정하거나 시계를 뒤로/앞으로 조작하지 않는다.
- 반례의 무승인/남의 예매/철회 확인·확인 재전송·ID 충돌·명확한 attempt 3·LLM 장애 4종·API flaky/error/slow·금액 없는 기록·staff 대조·본체/HTTP 하위 9개의 무인증 거절·복합 비권한 조회·context 주입의 mock 프롬프트 유입을 검사한다.

각 JSON 보고서에는 `ordinary_errors`, `strict_errors`, 요청·응답, 경과 시간, 전후 API/mock 스냅샷을 남긴다. 하나라도 실패하면 종료 코드는 1이다. setup/관측 API가 실패해도 무시하지 않고 infrastructure 실패로 기록한다. 시험 종료 때 fault와 mock을 정상으로 복원한다.

Claude 설계의 `400 request_id_conflict`는 공통 계약의 `400 {error:"invalid request",codes:[...]}`와 다르므로 충돌 비노출 검사와 별도로 형식 오류를 보고한다. 통과를 위해 이를 예외 허용하지 않았다. 반면 금액 없는 C-2004에서 상담 티켓을 만드는 행위 자체는 금지하지 않는다. 요구사항대로 근거 없는 금액 계산/노출만 금지한다.

## 직접 확인한 결과

- `python3 -B -m unittest -v test_harness`: **14/14 통과**. 모드별 실제 HTTP 응답·SSE·임베딩/모델·호출 기록, 원본 판정 함수 동일성, 엄격 검사 실패 탐지, 헤더/URL/장애 hook 변환, repeat 순서 및 TM-09의 5회 준비를 확인했다.
- `docker compose -p ticketmoa-verify -f drafts/n8n/verify/compose.yml config --quiet`: 통과. Compose 파싱/설정 검사이며 이미지 존재/기동 검증은 아니다.
- `bash -n`으로 셸 스크립트 네 개 문법 검사: 통과.
- prepare-data 실제 실행 및 원본과 대조: 사용자 5명·기록 5건·팀 문서 8개, 내용 및 날짜 보존 확인.
- 확인 시점에 `drafts/n8n/workflows/`가 없어 **up 및 n8n 통합 시험은 실행하지 않았다**. 실제 업무 통과율은 아직 없다. 기존 컨테이너나 aio-t4에는 접근하지 않았다.

## 한계

1. mock은 계약/분기/오류 처리 fixture다. 실제 모델의 한국어 품질·검색 임베딩 품질·토큰 비용·서비스 지연을 검증하지 않는다. 개념별 결정적 3072차원 벡터에 소량 해시 잡음을 넣으며 단일 동일 개념 유사도 >0.8, 무개념/다른 개념 <0.2를 단위 검사했다. 여러 개념을 섞은 긴 문서는 일치 비율에 따라 점수가 낮아질 수 있다. 실제 측정값으로 오해하면 안 된다.
2. OpenAI embedding의 문자열 input과 base64 출력은 지원한다. 클라이언트가 토큰 ID 배열을 보내는 경우 의미를 임의 추정하지 않고 400으로 명확히 실패시킨다. 이 경우 통합 결과는 호환성 한계로 보고하고, 실제 키나 실제 API로 우회하지 않는다.
3. writer는 context에서 문장을 추출하므로 실제 LLM의 요약 품질을 흉내 내지 않는다. 출력 형식이나 ROLE 표지가 다르면 워크플로우에 맞춰 조용히 허용하지 않고 오류가 난다.
4. API 스냅샷은 응답 후 0.2초 유예를 두고 관측한다. 그보다 늦은 로그/알림은 누락으로 보고할 수 있다. slow POST의 지연 성공은 원본 API 특성상 8초 후 발생할 수 있어 즉시 스냅샷만으로 영구 미생성을 주장할 수 없다. 보고서에는 관측 시점의 값만 남긴다.
5. --repeat 3은 원본 도구와 같이 케이스별 같은 body/request_id의 연속 재전송이다. 독립 모델 평가 세 번이 아니다. 반례는 상태 순서를 지키기 위해 각 단계 한 번 실행한다. 별도 동시성/원자성·부하 시험은 구현하지 않았다.
6. 무인증 검사는 401/403과 티켓/mock 부작용 없음을 확인한다. 데이터 API 자체는 과정 원본처럼 X-Api-Key를 강제하지 않으며 n8n Header Auth 검사를 대신하지 않는다.
7. n8n import/publish, 이미지 가용성, Credential base URL 적용, 실제 memory store 수명, Error Workflow 연결은 아직 통합 확인하지 못했다. up은 이후 실행 시 이 격리 프로젝트만 사용하며 색인 전/후 결과를 남긴다. 셸/Compose 정적 검사 통과를 통합 성공으로 보고하지 않는다.

CODEX-2-DONE
