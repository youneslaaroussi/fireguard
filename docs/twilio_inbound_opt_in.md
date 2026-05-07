# Twilio Inbound Opt-In

FireGuard supports a real SMS opt-in path for demo recipients. This is not an official resident registry; it is a consented test-contact workflow for allowlisted Twilio demo numbers.

## Webhook

Configure the Twilio phone number's incoming message webhook:

```text
POST https://fireguard-api-dovhkdlznq-uc.a.run.app/resident-contacts/twilio/inbound
```

Keep `TWILIO_VALIDATE_WEBHOOK_SIGNATURE=true` in hosted environments. If the webhook is configured through a custom domain or another URL that differs from the request URL seen by Cloud Run, set `TWILIO_INBOUND_WEBHOOK_PUBLIC_URL` to the exact Twilio webhook URL.

## Recipient Commands

```text
JOIN ZONE_A
JOIN ZONE_B
JOIN ZONE_C
STOP ZONE_A
STOP ZONE_B
STOP ZONE_C
```

On `JOIN`, FireGuard stores:

- masked phone number;
- zone ID;
- Twilio message SID;
- consent timestamp;
- source type `twilio_inbound_opt_in`;
- whether the phone is present in `TWILIO_ALLOWLIST`.

Outbound SMS still requires the number to be in `TWILIO_ALLOWLIST`, so a random inbound sender cannot trigger outbound alert delivery.

## Hosted Verification

On `2026-05-07T17:46:23Z`, the hosted Cloud Run API received a real Twilio inbound SMS webhook from `TwilioProxy/1.1` at:

```text
POST /resident-contacts/twilio/inbound
```

The request returned HTTP 200 and stored `ZONE_C` as a non-synthetic Twilio opt-in contact with masked phone `+1***6110` and Twilio message SID `SMbbfa5e9f4a789d5ab67773b09886d992`.

The next hosted assessment completed Gemini and the Zone C resident SMS action carried:

```text
INPUT_ZONE_C_ZONE_OPERATIONS_OPERATOR_CONFIRMED
INPUT_ZONE_C_CONTACT_TWILIO_OPT_IN
```

No synthetic Zone C contact placeholder or stale derived Zone C vulnerable/access assumption was attached to that action.
