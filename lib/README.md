# 공통 함수 (`lib/common.js`)

n8n Code 노드는 기본 설정에서 로컬 파일을 불러올 수 없다. 그래서 **`common.js`가 원본**이고, 필요한 함수만 Code 노드 맨 위에 복사해 쓴다.

**규칙**
- 함수를 고치려면 `common.js`를 고치고 `node --test lib/test/*.test.js`를 통과시킨 뒤, 그 함수를 쓰는 노드에 다시 복사한다. 노드 안에서만 고치지 않는다.
- 숫자 기준(500자, 3회, 0.7, 30만원, 30분)은 맨 위 상수에만 있다. 바꾸면 지식 문서·시나리오와 함께 바꾼다.
- 함수끼리 서로 부르지 않는다 (`ROUTES` 상수만 같이 복사).

## 함수 목록

| 함수 | 하는 일 | 쓰는 곳 (담당) | 관련 시나리오 |
| --- | --- | --- | --- |
| `validateRequest(body, users)` | 빈 질문·없는 사용자·501자 → `codes` | support (최두나) | WF-13 |
| `badRequest(codes)` | 400 본문 `{error, codes}` | support (최두나) | WF-13 |
| `detectInjection(text)` | 주입 문장 규칙 차단, LLM 전에 | support (최두나) | WF-08, TM-04 |
| `decideRoute(cls, req)` | 보완 질문 / 이관 / 처리 갈림 (LLM 아님) | support (최두나) | WF-02, 02b, TM-05 |
| `buildResponse(p)` | 공통 계약 9칸 채우기 + answer 가림 | support, 모든 하위 웹훅의 마지막 (모두) | 전부 |
| `parseAgentJson(raw, required, fallback)` | LLM 출력 JSON 읽기, 못 읽으면 fallback (이관) | agents (최강현) | 전부 |
| `calcRefund(b)` | 환불 수수료·환불액·마감·승인 필요 | refund (최강현) | TM-02, 03, 06 |
| `memoryKeysFor(user)` | 권한별 검색 메모리 키 (검색 전 필터) | search (정예진) | WF-05 |
| `urgencyFor(showStartISO, now)` | 공연 30분 이내 = high | tech (정예진) | WF-12 |
| `maskPII(text)` / `maskDeep(obj)` | 전화·이메일 가림, 가린 개수 | payment, handoff (심환석) | WF-06, 07 |
| `shouldRetry(status, errorCode)` | 429·5xx·timeout만 재시도 | handoff, payment (심환석) | WF-04, 11 |
| `backoffMs(attempt, retryAfter)` | 재시도 대기 시간 | handoff (심환석) | WF-04 |
| `checkRateLimit(recent, now)` | 같은 사용자 60초 5회 초과면 차단 (매크로 대응, 가산) | support 앞단 (심환석) | TM-09 |
| `checkIpPolicy(ip, policy)` | `context.client_ip`를 `config/ip-policy.json`으로 검사 (해외·블랙리스트, 가산) | support 앞단 (심환석) | TM-10~12 |
| `buildLog(req, res, extra)` | `/logs` 기록 (질문 원문·연락처 없음, channel 은 정규화) | support (최두나) | 결과서 |
| `normalizeChannel(v)` / `CHANNELS` | channel 을 web·app·phone·kiosk·email·other 로 제한 (연락처 원문 기록 방지) | support, handoff (심환석) | WF-07 |

## Code 노드에서 쓰는 예

```js
// ← 여기에 common.js의 ROUTES, validateRequest, badRequest, detectInjection을 복사
const body = $json.body;
const users = $('Load users').first().json.users;
const v = validateRequest(body, users);
if (!v.ok) return [{ json: { status: 400, body: badRequest(v.codes) } }];
const inj = detectInjection(body.question);
return [{ json: { ...body, user_info: v.user, injection: inj } }];
```
