# ESP32 PPP Firmware Guidelines

## Purpose
This note defines firmware-side behavior for PPP microcontroller (ESP32) receiving:
1. Driver profile over TCP (signed envelope)
2. OSC command packets over TCP (4-byte big-endian frame length + OSC datagram)
3. Telemetry profile/rules and periodic telemetry uplink.

## Control Plane Protocol
- TCP server on PPP (default configurable port).
- Profile envelope format (line-delimited JSON):
```json
{
  "type": "ppp_driver_profile",
  "signature": "hex(sha256(payload + signing_key))",
  "payload": "{...rule config json...}"
}
```

### Firmware recommendations
- Validate JSON schema before applying profile.
- Verify signature before commit.
- Keep active+previous profile and rollback on parse/apply failure.
- Save accepted profile to NVS/flash with version id.

## Data Plane Protocol
- OSC-over-TCP framed binary:
  - 4 bytes network-order length
  - raw OSC datagram bytes
- Firmware parses OSC address/args and maps to serial/RS commands via active profile rules.

## Telemetry
- Telemetry rules stored in profile:
  - source (register/sensor)
  - period
  - OSC address
- Firmware emits telemetry as OSC packets over TCP back to PSHU telemetry endpoint.

## Security baseline
- Keep signing key out of source control.
- Reject unsigned or invalid-signature profile envelopes.
- Add anti-replay nonce/version in next revision.

## Operational logging
- Log: profile received, signature result, profile applied version, command parse failures, serial tx errors, telemetry tx errors.
