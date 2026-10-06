# 위드유톡 AI 추론 서버 API 문서 v0.3.2

Oct 6, 2026 

https://might-diverse-tool-wood.trycloudflare.com

## 1. 개요

위드유톡 AI 추론 서버는 대화방 메시지를 받아 사이버불링 여부와 가해자·피해자를 판정합니다. 사건이 열려 있는 동안에는 주변인의 방어·동조·방관 행동을 추적해, 앱이 아이에게 보여 줄 알림을 돌려줍니다. v0.3.0은 v0.2.0에 방관행동 판정부(`/bystander/*`)를 더한 버전이고, v0.3.1은 피해자 식별을 보강했습니다. v0.3.2는 가해자·피해자 방향이 틀리던 문제를 고치고, 사건이 열린 뒤에도 피해자를 바로잡습니다 (§9).

| 항목 | 값 |
| --- | --- |
| 기본 주소 | 페이지 맨 위 링크 (임시 터널) |
| 형식 | JSON, UTF-8 (`Content-Type: application/json; charset=utf-8`) |
| 서버 버전 | 0.3.2 |

**개인정보 원칙**

- 모든 식별자는 가명 `participant_code`(예: `P05`)로 보냅니다. 전화번호, 학교명은 보내지 않습니다.
- `participants[].display_name`은 앱 화면에 보이는 이름입니다. 서버는 공격 메시지에서 이름을 찾는 데만 메모리로 쓰고 저장하지 않습니다.
- 1:1 대화 내용은 보내지 않습니다. 방어 기능을 사용했다는 사실만 이벤트로 보냅니다.
- `/bystander/state`의 판정 결과(방관 등)는 아동에게 보여 주지 않습니다.

## 2. 연동 흐름

앱은 메시지 하나마다 `/analyze`를 두 번 부르고, 주변인 이벤트는 따로 보고하며, 알림은 조회해서 가져옵니다.

&#91;embedded content: 앱–서버 호출 흐름 · 4가지 호출\]

실선은 요청, 점선은 응답입니다. ②는 메시지마다 한 번만 부릅니다. 두 번 부르면 사건과 주변인 판정이 두 번 계산됩니다. 서버에 `WITHU_ACTION_WEBHOOK`을 설정하면 ④ 대신 서버가 알림을 앱으로 POST합니다.

## 3. `GET /health` — 서버 상태 확인

두 값이 모두 `true`여야 정상입니다. `bystander_tracker`가 `false`이면 30초·60초 알림이 나가지 않습니다.

```json
{ "status": "ok", "ensemble_ready": true, "bystander_tracker": true }
```

| 필드 | 설명 |
| --- | --- |
| `ensemble_ready` | 판정 모델(모듈 A·B·D)이 모두 로드됨 |
| `bystander_tracker` | 방관행동 타이머 스레드가 실행 중 |

## 4. `POST /analyze` — 메시지 판정

새 메시지와 직전 대화(5\~10개)를 보내면 사이버불링 점수, 가해자·피해자 판정, 주변인 상태를 돌려줍니다. **개입 여부는 `attribution.is_bullying` 하나로 판단하세요.**

### 요청

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `room_id` | string | 예 | 대화방 ID |
| `new_message` | Message | 예 | 판정할 메시지 (아래 Message 표) |
| `context` | Message\[\] | 아니오 | 직전 대화, 오래된 것부터. 기본 `[]` |
| `participants` | Participant\[\] | 권장 | 대화방 구성원 명단. 피해자 이름 지목에 씁니다. 서버가 방별로 기억하므로 입장·변경 때만 보내도 되지만, 매번 보내도 됩니다 |
| `track_bystander` | boolean | 아니오 | 기본 `true`. 전송 전 호출은 `false`, 전송 후 호출은 `true`. 메시지마다 `true` 호출은 한 번만 |
| `has_image` | boolean | 시각적 폭력에 필요 | `new_message`가 이미지(사진·캡처)면 `true`. 기본 `false`. 이미지 바로 뒤에 다른 아이가 항의하면 그 이미지를 공격으로 셉니다 (0.3.2) |
| `left_chat` | boolean | 아니오 | 발신자가 대화방을 나갔는지. 기본 `false` |
| `logs` | object | 아니오 | 배제 판정(모듈 C)용 메타데이터. 현재 모듈 C는 비활성 |

**Message**

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `participant_code` | string | 예 | 발신자 가명 코드 |
| `text` | string | 아니오 | 메시지 본문. 기본 `""` |
| `message_id` | string | 강력 권장 | 앱의 메시지 ID. 반응 버튼·읽음 이벤트가 이 ID를 가리킵니다. 이미지·무마 발화로 열리는 사건은 이 ID가 있어야 추적됩니다 |
| `timestamp` | string | 권장 | ISO 8601. 없으면 서버 시각 |
| `is_defense_action` | boolean | 아니오 | 챗봇 방어행동 선택지로 보낸 메시지면 `true`. 기본 `false` |
| `read_by_count` | integer | 아니오 | 이 메시지를 읽은 인원 |
| `response_latency_sec` | number | 아니오 | 이 발신자가 응답하기까지 걸린 초 |
| `reply_to_message_id` | string | 아니오 | 답장 기능으로 보낸 메시지면 원래 메시지의 `message_id`. 공격 메시지가 답장이면 원래 발신자를 피해자로 지목합니다 |

**Participant**

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `participant_code` | string | 예 | 가명 코드 |
| `display_name` | string | 권장 | 앱 화면 이름. `김하늘`이면 `하늘아`, `하늘이가`도 찾습니다 |
| `aliases` | string\[\] | 아니오 | 아이들이 실제로 부르는 다른 이름(별명 등) |

```json
{
  "room_id": "room_001",
  "participants": [
    { "participant_code": "P11", "display_name": "내가최고다" },
    { "participant_code": "P03", "display_name": "하늘" },
    { "participant_code": "P05", "display_name": "별이" }
  ],
  "context": [
    { "participant_code": "P11", "text": "하늘 너 진짜 냄새나 꺼져", "message_id": "m1", "timestamp": "2026-10-05T14:21:40+09:00" },
    { "participant_code": "P03", "text": "왜 그래...", "message_id": "m2", "timestamp": "2026-10-05T14:21:52+09:00" }
  ],
  "new_message": { "participant_code": "P11", "text": "역겨우니까 나가라", "message_id": "m3", "timestamp": "2026-10-05T14:22:01+09:00" },
  "track_bystander": true
}
```

### 응답

| 필드 | 설명 |
| --- | --- |
| `attribution.is_bullying` | **개입 기준.** 사건 게이트를 통과한 사이버불링이면 `true` |
| `attribution.aggressors` | 가해자 코드 목록. `is_bullying=true`일 때만 신뢰 |
| `attribution.victim` | 피해자 코드. `is_bullying=true`일 때만 신뢰 |
| `attribution.victim_reason` | 피해자를 찾은 근거: `explicit_target`(답장), `name_mention`(이름), `repeated_target`(반복 공격에 같은 아이가 반응), `distress_signal`, `turn_adjacency` |
| `attribution.victim_support` | 피해자 근거의 세기 (0.3.2). `strong`: 답장·이름으로 지목됐거나 그 아이가 직접 2번 이상 항의함. `weak`: 공격 뒤에 반응했다는 것뿐 |
| `attribution.attack_message_ids` | 서버가 공격으로 센 메시지의 `message_id` 목록 (0.3.2). 무마 발화와 이미지도 들어갑니다 |
| `attribution.confidence` | 역할 판정 신뢰도 0\~1 |
| `attribution.drop_reason` | `is_bullying=false`인 이유 (예: `weak_target`). 디버그용 |
| `cb_score` | 메시지 단위 사이버불링 점수 0\~1 (가드 적용 후). 전송 전 경고에만 사용 |
| `cb_type` | `비해당`, `언어적 폭력`, `시각적 폭력`, `배제`, `composite` |
| `suppressed` | 위로·방어 발화로 판단되어 점수가 억제되었으면 `true` |
| `guard_reason` | 억제 사유. 없으면 `none` (예: `defense_action`) |
| `incident_id` | 이 대화방에 진행 중인 사건 ID. 없으면 `null` |
| `bystander_behavior` | 발신자가 주변인이면 현재 판정: `방어`, `동조`, `방관`, 또는 `null` |
| `bystander_state` | 사건과 주변인별 상태 (§7과 같은 형식). 연구 로그용, 아동에게 노출 금지 |
| `module_scores` | 모듈별 점수. 디버그용 |
| `evidence` | 판정 근거 한 줄 (한국어) |
| `intervention_needed` | 전환용. 현재 `is_bullying`과 같은 값 |
| `intervention_level` | **폐기 예정** (§9). 새 코드에서 쓰지 마세요 |

```json
{
  "room_id": "room_001",
  "cb_score": 0.97,
  "cb_type": "언어적 폭력",
  "suppressed": false,
  "guard_reason": "none",
  "attribution": {
    "is_bullying": true, "aggressors": ["P11"], "victim": "P03",
    "victim_reason": "name_mention", "victim_support": "strong",
    "attack_message_ids": ["m1", "m3"], "confidence": 1.0, "drop_reason": ""
  },
  "intervention_needed": true,
  "incident_id": "08e204d0f932",
  "bystander_behavior": null,
  "module_scores": { "...": 0.0 },
  "evidence": "가해자 ['P11'] → 피해자 P03 지목(name_mention), ..."
}
```

값은 형식을 보여 주는 예시입니다.

### 쓰는 법

- **전송 전 경고** (`track_bystander: false`): `cb_score`, `cb_type`, `suppressed`만 씁니다. 가드가 이미 적용되어 위로 메시지에는 경고가 나가지 않습니다.
- **전송 후 개입** (`track_bystander: true`): `attribution.is_bullying`이 `true`일 때만 가해자·피해자 기반 기능을 켭니다. `false`일 때의 `aggressors`, `victim`은 잠정값입니다.
- `cb_score` 하나로 개입하지 마세요. 평범한 대화도 0.5 안팎이 나올 수 있습니다 (§10).
- 챗봇 선택지로 보낸 위로 메시지는 `is_defense_action: true`로 보내세요. 이 표시가 없으면 가드가 덜 확실하게 작동합니다.

### 사건이 열리는 조건

공격 메시지가 있고, 피해자가 다음 중 하나로 특정되어야 합니다. 서버는 방마다 최근 60개·20분 메시지를 기억해서 `context`보다 긴 흐름을 봅니다.

| 근거 | 조건 |
| --- | --- |
| `explicit_target` | 공격 메시지가 그 아이의 메시지에 대한 답장 (`reply_to_message_id`) |
| `name_mention` | 공격 메시지에 그 아이의 `display_name`/`aliases`가 나옴. 공격 2개 이상, 또는 그 아이가 공격 직후 반응하면 열림 |
| `repeated_target` | 이름이 없어도, 한 가해자의 공격이 4개 이상이고 같은 아이가 공격 직후 2번 이상 반응. 반응 수는 (항의 + 그 밖의 반응 − 맞장구)로 셉니다 |

피해자도 같이 욕하면(서로 욕하는 장난) 사건이 열리지 않습니다.

### 메시지 성격 (0.3.2)

공격 뒤에 말했다고 모두 피해자는 아닙니다. 서버는 메시지마다 성격을 보고 방향을 정합니다. 낱말 규칙이며 모델 점수와는 별개입니다.

| 성격 | 예 | 처리 |
| --- | --- | --- |
| 항의 | 하지 말라고, 그만해, 지워줘, 왜 나만, ㅠㅠ | 피해자 근거. 점수가 높아도 공격으로 세지 않음 |
| 맞장구 | ㅇㅈ, 팩트, ㄹㅇ, 맞아, ㅋㅋ | 가해자 편으로 봄. 반응 수에서 뺌 |
| 무마 | 장난인데, 왜 화냄?, 예민하네 | 바로 앞(3개 안)에 다른 아이의 항의가 있으면 공격으로 셈 |
| 말리기 | 그만 싸워, 너무 심하잖아, 얘들아 진정해 | 주변인의 방어. 공격으로도 피해자 근거로도 세지 않음 |
| 이미지 | `has_image: true` | 바로 뒤(3개 안)에 다른 아이의 항의가 있으면 공격으로 셈 |

욕설이 섞인 항의("그만해 병신아")는 되받아치는 것으로 보고 공격으로 셉니다. 웃음이 섞인 항의("아 하지마 ㅋㅋㅋ")는 근거로 쓰지 않습니다.

## 5. `POST /bystander/events` — 앱 이벤트 보고

읽음, 퇴장, 재입장, 반응, 방어 기능 사용이 생길 때마다 보냅니다. 방관 판정은 이 이벤트에 달려 있습니다. 읽음 이벤트가 없으면 말하지 않은 아이는 판정되지 않습니다.

```json
{ "room_id": "room_001", "participant_code": "P05", "type": "read",
  "timestamp": "2026-10-05T14:22:03+09:00", "message_id": "m3" }
```

응답: `{ "ok": true, "actions": [ … ] }`. `actions`는 이 대화방에 쌓인 알림이며 §6과 형식이 같습니다. 여기서 받은 알림은 `/bystander/actions`에서 다시 나오지 않습니다.

| `type` | 보낼 때 | 추가 필드 |
| --- | --- | --- |
| `read` | 아이 화면에 새 메시지가 표시될 때마다 | `message_id` (마지막으로 본 메시지), `unread_count` (선택) |
| `room_open` | 대화방에 들어올 때 | `unread_count` |
| `join` | 나갔던 대화방에 다시 들어올 때 | — |
| `leave` | 대화방을 나갈 때 | `normal`: 직접 나감 `true` (기본), 앱 오류·네트워크 끊김·강제 종료 `false` |
| `reaction` | 메시지에 반응 버튼을 누를 때 | `target_message_id` 또는 `target_participant_code`, `reaction` |
| `reaction_cancel` | 반응을 취소할 때 | — |
| `defense_action` | 챗봇의 방어행동 선택지를 실행할 때 | `kind`: `comfort_dm`, `stop_dm`, `tell_adult`, `topic_change`, `report` |
| `summary_shown` | 요약(`summary`)을 화면에 표시했을 때 | — |
| `decline` | 알림을 "괜찮아/닫기"로 거절할 때 | — |
| `not_bullying` | "괴롭힘이 아닌 것 같아"를 고를 때 | — |

공통 필드: `room_id`, `participant_code`, `type`은 필수이고 `timestamp`(ISO 8601)는 없으면 서버 시각을 씁니다.

`reaction` 값: `like`, `empathy`, `sad`, `heart`, `laugh`, `dislike`, `angry`. 한국어 이름(`좋아요`, `공감`, `웃겨요`, `싫어요`, `화나요` 등)도 받습니다.

챗봇 선택지로 위로 메시지를 보낼 때는 `/analyze`의 `is_defense_action: true`와 `defense_action` 이벤트를 **둘 다** 보내세요.

## 6. `GET /bystander/actions?room_id=…` — 표시할 알림 가져오기

대화방이 열려 있는 동안 2\~5초마다 호출합니다. **각 알림은 한 번만 반환**되므로 받은 즉시 처리하고, `participant_code`가 가리키는 아이 화면에만 표시합니다.

```json
{ "room_id": "room_001", "actions": [
  { "action_id": "74a296d941f9", "room_id": "room_001", "incident_id": "08e204d0f932",
    "participant_code": "P05", "action": "nudge_1",
    "text": "가만히 있는다면 공격받는 친구가 힘들어 할거야.",
    "created_at": "2026-10-05T14:22:33", "payload": {} } ] }
```

| `action` | 언제 나오나 | 앱 동작 | `payload` |
| --- | --- | --- | --- |
| `incident_open` | 사건 시작 | 상황 알림 배너 등. `participant_code` 없음 | `aggressors`, `victim`, `victim_reason`, `victim_status` |
| `incident_update` | 피해자가 바뀌거나(`change: victim_changed`) 확정됨(`change: victim_confirmed`) (0.3.2) | 아래 "피해자가 바뀔 때" 참고. `participant_code` 없음 | `change`, `aggressors`, `victim`, `victim_reason`, `victim_status`, 바뀐 경우 `previous_victim`, `previous_victim_role`, `new_victim_was_bystander` |
| `nudge_1` | 노출 후 30초 무반응, 또는 무관한 대화 | 1차 알림: 챗봇 말풍선 | — |
| `nudge_2` | 노출 후 60초 무반응 (방관 확정) | 2차 알림 + 방어행동 선택지 | `choices: true` |
| `summary` | 사건 후 10분 넘어 처음 봄, 또는 안 읽은 메시지 30개 이상 | 사건 요약을 먼저 표시한 뒤 `summary_shown` 전송 | `aggressors`, `victim`, `n_attack_messages`, `first_attack_at`, `last_attack_at` |
| `badge` | 방관 상태로 정상 퇴장 | 채팅방 목록·푸시에 사건 표시 | — |
| `choices` | 방관 상태로 나갔다가 재입장 | 방어행동 선택지를 바로 표시 | — |
| `positive_feedback` | 방어행동 판정 | 짧은 긍정 피드백 | — |
| `join_feedback` | 동조 판정 | 영향 안내. 반응 버튼이면 취소 가능 | `cancel_window_sec` (반응 버튼 10, 발화 0) |

`text`는 서버의 권장 문구이며 최종 문구는 앱에서 정합니다. `incident_open`, `incident_update`처럼 문구가 없는 알림은 `text`가 `null`입니다.

**피해자가 바뀔 때 (`incident_update`, `change: victim_changed`)**

```json
{ "action": "incident_update", "participant_code": null, "incident_id": "08e204d0f932",
  "payload": { "change": "victim_changed", "aggressors": ["P11", "P07"], "victim": "P03",
               "victim_reason": "name_mention", "victim_status": "confirmed",
               "previous_victim": "P07", "previous_victim_role": "가해자",
               "new_victim_was_bystander": "방어" } }
```

- `previous_victim`에게 진행 중이던 피해자용 기능(1:1 위로 메시지 등)을 멈추고, `victim`에게 시작합니다.
- `new_victim_was_bystander`가 `null`이 아니면 새 피해자가 그동안 주변인으로 분류되어 알림을 받았다는 뜻입니다. 화면에 남은 주변인용 알림을 닫습니다.
- `previous_victim_role`은 이전 피해자의 새 역할입니다 (`가해자` 또는 `주변인`).

**`victim_status`** 는 `provisional`(근거가 공격 뒤 반응뿐) 또는 `confirmed`(답장·이름으로 지목됐거나 그 아이가 직접 2번 이상 항의함)입니다. `provisional`일 때는 피해자를 특정하는 기능(1:1 위로 메시지, 교사 알림 카드의 이름)을 미루고 `confirmed`가 된 뒤에 내보내기를 권장합니다. 주변인 알림은 `provisional`에서도 그대로 나갑니다.

## 7. `GET /bystander/state?room_id=…&participant_code=…` — 상태 조회

디버그와 연구 로그용입니다. **아동에게 노출하지 마세요.** `participant_code`를 빼면 모든 주변인을 돌려줍니다. 진행 중인 사건이 없으면 `incident`는 `null`입니다.

```json
{ "room_id": "room_001", "incident": {
  "incident_id": "08e204d0f932", "active": true,
  "aggressors": ["P11"], "victim": "P03", "victim_reason": "name_mention",
  "victim_status": "confirmed", "previous_victims": [], "n_attack_messages": 3,
  "first_attack_at": "2026-10-05T14:21:40", "last_attack_at": "2026-10-05T14:22:01",
  "bystanders": [
    { "participant_code": "P05", "stage": "defended", "behavior": "방어", "subtype": null,
      "exposed_at": "2026-10-05T14:22:03", "decided_at": "2026-10-05T14:23:10",
      "nudges": 2, "badge": false, "declined": false,
      "history": [ { "t": "2026-10-05T14:23:10", "event": "행동 전환: 방관→방어" } ] } ] } }
```

| 필드 | 값 |
| --- | --- |
| `victim_reason` | 지금 피해자를 뒷받침한 가장 강한 근거 (0.3.2) |
| `victim_status` | `provisional` 또는 `confirmed` (§6) (0.3.2) |
| `previous_victims` | 이 사건에서 피해자였다가 바뀐 아이들 (0.3.2) |
| `stage` | `unseen`, `observing`, `candidate`, `confirmed`, `left`, `defended`, `joined`, `closed` (§8) |
| `behavior` | `방어`, `동조`, `방관`, 또는 `null` |
| `subtype` | 방관일 때만: `침묵`, `채팅방 나가기`, `무관 대화` |
| `nudges` | 이 사건에서 받은 알림 수 (최대 2) |
| `badge` | 방관 상태로 나가서 배지가 표시 중 |
| `declined` | 알림을 거절했거나 괴롭힘이 아니라고 답함. 이후 알림 없음 |
| `history` | 최근 10개 상태 변화 |

## 8. 방관행동 판정 규칙

가해자도 피해자도 아닌 구성원(주변인)은 공격 메시지를 읽은 뒤 60초 동안 방어도 동조도 하지 않으면 방관(침묵)으로 판정됩니다. 사건은 `/analyze`의 `is_bullying`이 `true`가 될 때 열립니다.

&#91;embedded content: 주변인 상태 변화 · 7단계\]

방어·동조·퇴장은 노출된 세 단계 어디에서든 일어날 수 있습니다. 상태가 바뀔 때마다 알림(§6)이 하나씩 쌓입니다.

- **무관한 대화**를 하면 30초를 기다리지 않고 바로 `candidate`(방관: 무관 대화)가 되고 `nudge_1`이 나갑니다.
- **비정상 종료**(`leave`, `normal: false`)는 방관이 아닙니다. 타이머는 계속 돕니다.
- **읽지 않은 아이**는 퇴장해도 판정하지 않습니다.
- **늦게 본 아이**(마지막 공격 후 10분 이상, 또는 안 읽은 메시지 30개 이상)에게는 `summary`가 먼저 나갑니다. 시계는 `summary_shown`부터 다시 잽니다.
- **알림은 사건당 아이 1명에게 최대 2회**입니다. `decline`이나 `not_bullying` 뒤에는 더 보내지 않습니다.
- **방관→방어, 동조→방어 전환**은 `history`에 기록됩니다.
- 새 공격 없이 30분이 지나면 사건이 닫히고, 아직 판정 전인 주변인은 `closed`가 됩니다.

**피해자 갱신 (0.3.2)**

사건이 열린 뒤에도 `/analyze` 판정을 따라 피해자를 고칩니다. v0.3.1까지는 처음 잡힌 피해자가 사건이 끝날 때까지 남았습니다.

| 새 판정 | 피해자가 바뀌는 때 |
| --- | --- |
| 지금 피해자가 가해자로 판정됨 | 바로 |
| 더 강한 근거로 다른 아이가 피해자로 나옴 (답장 > 이름 > 반응) | 바로 |
| 같은 세기의 근거 | 2번 연속 |
| 더 약한 근거 | 3번 연속 |

바뀌면 `incident_update`가 나가고, 새 피해자는 가해자·주변인 목록에서 빠집니다. 한 아이가 가해자이면서 피해자인 상태는 생기지 않습니다. 이미 나간 알림(잘못 잡힌 피해자에게 간 위로 메시지, 진짜 피해자에게 간 방관 알림)은 서버가 되돌릴 수 없으므로 앱이 `incident_update`를 받아 정리합니다.

**반응 버튼 판정** (반응을 누른 메시지의 발신자 기준)

| 반응 대상 | 공감·슬퍼요·하트 | 좋아요 | 웃겨요 | 싫어요·화나요 |
| --- | --- | --- | --- | --- |
| 피해자 메시지 | 방어 | 방어 | 동조 | 동조 |
| 가해자 메시지 | 판정 없음 | 동조 | 동조 | 방어 |

반응 버튼으로 동조가 된 경우 10초 안에 `reaction_cancel`을 보내면 동조 판정이 취소되고 이전 단계로 돌아갑니다.

## 9. v0.2.0 대비 변경 사항

기존 필드는 모두 그대로 동작합니다. 새 필드와 엔드포인트를 더했고, `intervention_level`은 다음 버전에서 삭제합니다.

| 구분 | 항목 | 내용 |
| --- | --- | --- |
| 수정 (0.3.2) | 피해자 고정 | 사건이 열린 뒤 피해자가 바뀌지 않던 문제. 이제 판정을 따라 갱신 (§8) |
| 수정 (0.3.2) | `repeated_target` 방향 | 맞장구친 같은 편이 피해자로 잡히거나, 피해자의 항의가 공격으로 세어져 가해자·피해자가 뒤바뀌던 문제 (§4 메시지 성격) |
| 추가 (0.3.2) | `incident_update` (알림) | 피해자 변경·확정을 앱에 알림 (§6) |
| 추가 (0.3.2) | `victim_status`, `victim_reason`, `previous_victims` | 사건 상태와 `incident_open`·`incident_update` payload |
| 추가 (0.3.2) | `attribution.victim_support`, `attribution.attack_message_ids` | 피해자 근거의 세기, 공격으로 센 메시지 |
| 변경 (0.3.2) | `has_image` | 이미지 뒤에 다른 아이가 항의하면 그 이미지를 공격으로 셈. 시각적 폭력 판정에 필요 |
| 추가 (0.3.1) | `participants` (요청) | 대화방 명단. 피해자 이름 지목에 사용 |
| 추가 (0.3.1) | `reply_to_message_id` (요청의 Message) | 답장 대상. 피해자 지목에 사용 |
| 추가 (0.3.1) | `victim_reason: repeated_target` | 이름 없이 반복 공격 + 피해자 반응으로 사건이 열림 |
| 변경 (0.3.1) | `name_mention` | 본문에서 participant_code 대신 `display_name`/`aliases`를 찾음. 공격 2개 이상 또는 지목된 아이의 반응이 필요 |
| 추가 | `message_id` (요청의 Message) | 반응 버튼·읽음 이벤트가 메시지를 가리키는 데 필요 |
| 추가 | `track_bystander` (요청) | 전송 전 `false`, 전송 후 `true` |
| 추가 | `incident_id`, `bystander_state` (응답) | 사건 ID와 주변인 상태 |
| 추가 | `attribution`, `suppressed`, `guard_reason` (응답) | v0.2.0에서 스키마에 없어 빠지던 필드를 정식으로 선언 |
| 추가 | `POST /bystander/events` | 앱 이벤트 보고 |
| 추가 | `GET /bystander/actions` | 알림 조회 |
| 추가 | `GET /bystander/state` | 상태 조회 (디버그·연구 로그) |
| 추가 | `GET /health`의 `bystander_tracker` | 타이머 스레드 상태 |
| 폐기 예정 | `intervention_level` (`none`/`suspect`/`confirm`) | 0.75·0.85 임계값 단계. 다음 버전에서 삭제 → `attribution.is_bullying` 사용 |
| 전환용 | `intervention_needed` | 현재 `is_bullying`과 같은 값. 새 코드는 `is_bullying`을 직접 사용 |

**앱이 할 일**

1. 모든 메시지에 `message_id`를 붙이고, `/analyze`에 `participants`를 보냅니다. 답장 기능이 있으면 `reply_to_message_id`도 보냅니다.
2. 전송 전 호출에 `track_bystander: false`, 전송 후 호출에 `true`를 보냅니다.
3. 읽음, 퇴장, 재입장, 반응, 방어 기능 사용을 `POST /bystander/events`로 보냅니다.
4. `GET /bystander/actions`를 2\~5초마다 조회해 해당 아이 화면에만 알림을 표시합니다.
5. `intervention_level`에 걸린 개입 동작을 `attribution.is_bullying` 기준으로 옮깁니다.
6. (0.3.2) `incident_update` 알림을 처리합니다. 피해자가 바뀌면 피해자용 기능을 새 피해자로 옮깁니다 (§6).
7. (0.3.2) 피해자를 특정하는 기능은 `victim_status`가 `confirmed`일 때 내보냅니다 (권장).
8. (0.3.2) 이미지 메시지도 `/analyze`로 보내고 `has_image: true`를 붙입니다. 본문이 없으면 `text`는 `""`로 보냅니다.

## 10. 알려진 제약

가장 큰 제약은 사건 상태가 서버 메모리에만 있다는 점입니다. 서버를 재시작하면 진행 중인 사건과 주변인 상태가 사라집니다.

- **서버 재시작 시 상태 손실.** 사용성 평가 규모에서는 괜찮지만, 여러 반이 오래 쓰는 효과성 평가 전에는 SQLite나 Redis 저장이 필요합니다. 연구 로그가 필요하면 `/bystander/state`를 주기적으로 저장하세요.
- **주소가 바뀝니다.** 현재 임시 Cloudflare 터널이라 서버를 다시 켜면 기본 주소가 바뀝니다.
- **피해자 식별의 한계.** 피해자가 말하지 않고 이름도 불리지 않으면 사건이 열리지 않습니다. 실명·별명으로 부르면 `aliases`에 있어야 이름으로 잡힙니다.
- **방향 판정은 낱말 규칙입니다 (0.3.2).** 항의·맞장구·무마·말리기를 정해진 표현으로 찾습니다. 목록에 없는 표현은 평범한 반응으로 처리됩니다. 말리는 주변인이 "하지 마"처럼 피해자와 같은 표현만 쓰면 피해자 후보로 잡힐 수 있습니다. 그래서 반응만으로 잡힌 피해자는 `provisional`로 표시합니다.
- **방에 없는 피해자.** 대화방에 없어도 `participants`에 있으면 이름으로 피해자로 지목됩니다. `participants`에 없으면 사건이 열리지 않습니다 (예전처럼 같은 편 아이가 피해자로 잡히지는 않습니다). 방에 없는 아이에게 무엇을 보낼지는 정해지지 않았습니다.
- **시각적 폭력.** 서버는 이미지 내용을 보지 않습니다. `has_image`와 뒤따르는 항의·무마 발화로만 판단합니다. 이름·답장 지목이 없으면 공격으로 센 메시지가 4개 이상이어야 열립니다.
- **방 기록도 메모리에만 있습니다.** 서버 재시작 시 방별 최근 메시지와 명단이 사라집니다.
- **대화방당 사건 하나.** 같은 방에서 공격이 이어지면 같은 사건에 더해집니다. 새 공격 없이 30분이 지나면 사건이 닫힙니다.
- **`cb_score` 단독 사용 금지.** 2026-09-30 실서버 테스트에서 평범한 대화가 0.53, `is_defense_action` 표시 없는 위로 메시지("네 잘못이 아니야.")가 0.315로 나왔습니다. 개입은 `is_bullying`으로 판단하세요.
- **배제(모듈 C) 비활성.** 실제 메신저 로그가 쌓이기 전까지 `cb_type`에 `배제`는 나오지 않습니다.
- **주변인 발화 판정.** 서버가 LLM(모듈 D)을 켠 경우 LLM으로, 끈 경우 보수적인 키워드 규칙으로 판정합니다. 침묵 타이머는 어느 쪽이든 동작합니다.

## 부록. 서버 실행과 테스트 (연구팀용)

서버는 `withu/` 패키지를 **담고 있는 폴더**에서 실행합니다. 방관 판정 상태가 메모리에 있어서 워커가 여럿이면 요청마다 다른 상태를 봅니다.

**터미널 1 — 서버**

```bash
source ~/python313_env/bin/activate
source ~/.withu_secrets          # OPENAI_API_KEY 등. 이 파일은 저장소에 올리지 않습니다
cd ~/Downloads
ENABLE_BYSTANDER=1 uvicorn withu.app:app --host 0.0.0.0 --port 8000 --workers 1
```

**터미널 2 — 로컬 확인 후 터널 열기**

```bash
curl http://localhost:8000/health
~/bin/cloudflared tunnel --url http://localhost:8000
```

**터미널 3 — 외부 주소 확인**

```bash
curl https://<터널이 출력한 주소>.trycloudflare.com/health
```

터널 주소가 바뀌면 앱 개발사에 새 주소를 알려 주세요. 두 세션 모두 `tmux` 안에서 실행하면 접속이 끊겨도 유지됩니다.

**설정값 (환경변수)**

| 변수 | 기본값 | 의미 |
| --- | --- | --- |
| `ENABLE_BYSTANDER` | 꺼짐 | `1`이면 주변인 발화를 LLM(모듈 D)으로 판정 |
| `BYSTANDER_T1_SEC` | 30 | 노출 후 1차 알림까지 (초) |
| `BYSTANDER_T2_SEC` | 60 | 노출 후 방관 확정 + 2차 알림까지 (초) |
| `BYSTANDER_MAX_NUDGES` | 2 | 사건당 아이 1명에게 보내는 최대 알림 수 |
| `BYSTANDER_LATE_SEC` | 600 | 사건 후 이만큼 지나 처음 보면 요약 먼저 (초) |
| `BYSTANDER_SUMMARY_UNREAD` | 30 | 안 읽은 메시지가 이 이상이면 요약 먼저 |
| `BYSTANDER_CANCEL_SEC` | 10 | 동조 반응 취소 인정 시간 (초) |
| `BYSTANDER_IDLE_CLOSE_SEC` | 1800 | 새 공격 없이 이만큼 지나면 사건 종료 (초) |
| `WITHU_ACTION_WEBHOOK` | 없음 | 설정하면 알림을 조회 대신 이 URL로 POST |
| `WITHU_REPEAT_MIN_ATTACKS` | 4 | 반복 표적: 가해자 1명의 공격 수 |
| `WITHU_REPEAT_MIN_REPLIES` | 2 | 반복 표적: 같은 아이의 반응 수 |
| `WITHU_NAME_MIN_ATTACKS` | 2 | 이름 지목만으로 열리는 공격 수. 지목된 아이가 반응하면 1 |
| `WITHU_HISTORY_MAX_MSGS`, `WITHU_HISTORY_MAX_SEC` | 60, 1200 | 방별 기록 길이와 보존 시간 |
| `WITHU_ENABLE_REPEAT` | 1 | `0`이면 반복 표적 끔 |
| `WITHU_ENABLE_RESIST_GUARD` | 1 | `0`이면 항의·말리기 발화도 점수대로 공격으로 셈 (0.3.1 동작) |
| `WITHU_ENABLE_PSEUDO_ATTACK` | 1 | `0`이면 무마 발화·이미지를 공격으로 세지 않음 |
| `WITHU_REPEAT_MIN_PROTEST` | 0 | 반복 표적에 꼭 있어야 하는 항의 반응 수. `1` 이상이면 더 엄격 |
| `WITHU_PROTEST_REPLY_WEIGHT` | 3.0 | 항의 반응 1번의 점수 (그 밖의 반응 2, 맞장구 −2) |
| `BYSTANDER_VICTIM_SWITCH_SAME`, `BYSTANDER_VICTIM_SWITCH_WEAKER` | 2, 3 | 피해자 교체에 필요한 연속 판정 수 (같은 세기, 더 약한 세기) |
| `SUSPECT_THRESHOLD`, `CONFIRM_THRESHOLD` | 0.75, 0.85 | `intervention_level`용. 폐기 예정 |

**실서버 테스트**

서버를 켠 상태에서 `python test_live_server.py`를 실행합니다. 피해자 식별은 `python test_target_live.py`로 따로 확인합니다. 2026-09-30 결과(v0.3.0)는 필수 항목 25/25 통과, 참고 항목 4/6이었습니다. v0.3.2 확인은 표 아래에 있습니다. 참고 항목 경고 2개는 §10의 `cb_score` 제약과 같은 내용입니다.

| 영역 | 결과 |
| --- | --- |
| 상태 확인 | 통과 |
| 가드 (`is_defense_action` 위로 메시지 → 0점) | 통과 |
| 사건 게이트 (서로 장난치는 대화 → 사건 없음) | 통과 |
| 실제 공격 → 사건 생성, 가해자·피해자 식별 | 통과 |
| 모듈 D 발화 판정 (방어·동조·방관) | 3/3 기대대로 |
| 반응 버튼, 10초 취소 | 통과 |
| 퇴장·비정상 종료·재입장·지연 목격 요약 | 통과 |
| 침묵 타이머 30초·60초, 알림 최대 2회 | 통과 |
| 방관→방어 전환과 긍정 피드백 | 통과 |

**v0.3.2 확인 (2026-10-06)**

모델 없이 도는 테스트는 통과했습니다. 실제 모델과 실제 사후·추수검사 대본 8편으로는 아직 확인하지 않았습니다.

```bash
cd ~/Downloads
python withu/test_target_resolver.py      # 기존 14개
python withu/test_victim_direction.py     # 피해자 갱신·방향 판정 19개
python test_scripts_live.py --base http://127.0.0.1:8000 사후1.json …   # 서버를 켠 뒤, 대본 JSON으로
```

| 확인 | 결과 |
| --- | --- |
| 기존 단위 테스트 (`test_target_resolver.py`) | 14/14 |
| 새 단위 테스트 (`test_victim_direction.py`) | 19/19 |
| 같은 대본을 v0.3.1 코드에 넣었을 때 | 보고된 오류 3가지가 그대로 재현됨 (같은 편이 피해자, 방에 없는 피해자 대신 같은 편, 가해자·피해자 뒤바뀜) |
| 기존 실서버 테스트 (`test_live_server.py`, 모델 대신 욕설 사전) | 필수 25/25, 수정 전과 같음 |
| 검증 코퍼스 (WCB001\~005, 발화자를 코드로 바꿔 흘려 보냄) | 사건 5/5 유지. 피해자 일치 89.3% → 88.0%, 사건 밖 오탐 41 → 46건 |

새 단위 테스트의 대본은 앱팀 보고에 나온 대사에 가상의 앞부분을 붙인 것이고, 점수도 실제 모델 값이 아닙니다. 검증 코퍼스에는 이번 오류 유형(맞장구, 항의, 무마)이 거의 없어서 개선도 악화도 뚜렷하지 않습니다. 코퍼스의 피해자 반응 170개 중 항의 표현은 10개뿐이었습니다. 실제 효과는 `test_scripts_live.py`로 대본을 다시 돌려서 확인해야 합니다.
