# API

The full contract is [openapi.yaml](openapi.yaml) (OpenAPI 3.1). Summary:

## Device API (`/api/device/v1`, Box B)

Every request carries `X-GK-Device`, `X-GK-Timestamp`, `X-GK-Nonce` and `X-GK-Signature`:

```
signature = hex(HMAC_SHA256(secret, METHOD + "\n" + PATH_WITH_QUERY + "\n" + TIMESTAMP + "\n" + NONCE + "\n" + hex(SHA256(body))))
```

| Call | When | Notes |
|---|---|---|
| `POST /readings` | every 30 min (:00 / :30) | returns `decision` and, if the node's version is behind, `settings` |
| `GET /poll?p&v&src&sv&m&w&rem&s` | every 3 s | ≤ 300 bytes; delivers `start` / `stop` / `read_now` commands |
| `POST /commands/{id}/ack` | after a command | `executed` or `rejected` (with a reason) |
| `POST /events` | each cycle, power change, boot | idempotent by `uuid` |
| `POST /sync` | after an offline period | readings get `synced_offline=true` and no new decision |
| `GET /settings` | when the poll shows a newer version | compact settings object |

`DeviceClient` in `backend/tests/conftest.py` signs requests exactly like the firmware and is the reference client.

## Dashboard API (`/api/v1`)

Session cookie (`gk_session`, HttpOnly, Secure, SameSite=Strict) and `X-CSRF-Token` on every
POST / PATCH. Role checks happen on the server for every route. Errors use one shape:

```json
{"error": {"code": "validation_error", "message": "Some settings are outside their allowed range.", "fields": {"moisture_threshold": "range 5–60"}}}
```

Managers get `401 reauth_required` for settings, user and device changes when their last password
entry is older than 15 minutes; `POST /auth/reauth` then retries.

## Compatibility API (`/api/sensors`)

For `firmware/legacy_single_probe` only, enabled with `GK_LEGACY_DEVICE_API=true`.
Authenticated with `X-Device-Key` (the device secret) over HTTPS. One reading per 30-minute slot is stored.
