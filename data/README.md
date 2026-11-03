# 티켓모아 데이터 초안 안내

2026-10-29 초안. 모두 **가짜 데이터**이며, 사람이 읽고 고친 뒤 팀 저장소 `knowledge/`, `data/`에 넣는다 (11-TOPIC-GUIDE 3절).

## 지식 문서 (`knowledge/`, 8개, 문서마다 `##` 절 4~5개)

| 문서 | access_level | 쓰이는 시나리오 |
| --- | --- | --- |
| `mobile-ticket-troubleshooting` | all | WF-01 (QR이 회색), 팀: 게이트 인식 실패 |
| `onsite-entry-fallback` | all | WF-12 (공연 직전 QR, 대체 입장 + 현장 알림) |
| `app-login-troubleshooting` | all | 앱·계정 문의 자동 답변 |
| `payment-error-guide` | all | 팀: 이중결제 → 이관 |
| `refund-policy` | all | 팀: 환불 2단계 확인, 30만원 초과 이관, 당일 취소 이관 |
| `venue-faq` | all | 데모 2 (주차) |
| `fair-booking-policy` | all | TM-07 (매크로 제한 해제), TM-08 (암표 신고 → 이관), TM-10 해외 IP 안내 |
| `staff-entry-manual` | **staff** | WF-05 (일반 고객이 수기 입장 절차 질문 → 이 문서를 근거로 쓰지 않음) |

- 권한 필터는 검색 **전에**: 메모리 키를 `ticketmoa_kb_v1_all`, `ticketmoa_kb_v1_staff`로 나누고 사용자 `access_level`에 맞는 키만 검색 (05-RAG-DESIGN-GUIDE 6절).
- 일부러 넣은 숫자(QR 3시간 전, 30분 전, 수수료 표, 30만원, 4시간 3,000원 등)는 문서끼리 서로 맞춰 두었다. 고칠 때는 `refund-policy`와 기획서의 이관 조건(30만원), `onsite-entry-fallback`과 `mobile-ticket-troubleshooting`의 "30분"을 함께 고친다.

## 사용자 (`data/users.json`, 5명)

| 이름 | 구분 | 권한 | 시나리오에서 |
| --- | --- | --- | --- |
| 김하늘 | 일반 고객 | all | C-2002 주인, WF-12 |
| 이도윤 | 일반 고객 | all | C-2003·C-2005 주인, WF-07 (내 건 + 연락처 → 가림), TM-02·03 환불 |
| 박서준 | 일반 고객 | all | C-2004 주인, WF-06 (C-2001 조회 → 권한 없음) |
| 정민아 | VIP 고객 | all | C-2001 주인 (이중결제), C-2006 주인 (TM-13 환불 30만원 초과) |
| 최현우 | 현장운영팀 | staff | 관리자 문서 검색 가능 (WF-05 대조군) |

## 접수 기록 (`data/records.json`, 6건)

기본 주제의 `tickets.json`과 같은 칸(`title, requester, status, assignee, updated, note, contact`)에 `booking_id, show, amount`를 더했다. 상태는 처리 중·접수됨·처리 완료·반려, C-2001~C-2004는 주인이 모두 다르다. C-2005(이도윤)는 환불 2단계 시나리오(TM-02·03)용 예매 건이다. C-2006(정민아, 352,000원)은 환불 30만원 초과 이관(TM-13)용이다. 예매번호 `T날짜-번호`의 날짜는 예매일이다. 연락처는 `010-0000-xxxx`, `@example.com`.

> 연습 환경: 78일차 데이터 API 복사본에서 `users.json`은 `employees.json`, `records.json`은 `tickets.json` 이름으로 넣는다 (`docs/PROMPTS.md` 0단계).

## 아직 안 한 것

- `cases/common.json` (공통 14개를 티켓모아 질문으로 옮긴 판, 80일차 8교시 강사 확인)
- `cases/team.json` (팀 시나리오 13개)
- 업무 레지스트리 JSON
