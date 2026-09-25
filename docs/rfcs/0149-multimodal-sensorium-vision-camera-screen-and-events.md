# RFC-0149: Multimodal Sensorium — screen, camera, audio and event perception

**Status:** accepted  
**Date:** 2026-09-24

## Problem
Anzu should understand its environment across screen/camera/device streams without sending continuous raw feeds into a large model or becoming an uncontrolled surveillance system.

## Decision
Introduce Sensorium adapters producing bounded observations from screen, cameras, microphones and device/system events. Lightweight local detectors perform change/event gating; expensive vision models run only when triggered or requested. Observations have source, timestamp, confidence, retention class and privacy zone. Users can disable streams, mask screen/camera regions and define no-record zones. Raw media defaults to ephemeral; durable memory stores derived observations only when policy permits.

## Acceptance criteria
- [ ] Multi-stream adapter API with backpressure and health state.
- [ ] Change/event gating materially reduces continuous model inference.
- [ ] Privacy masks/no-record zones are enforced before model ingestion.
- [ ] Raw retention defaults to ephemeral and is configurable per source.
- [ ] Sensor observations can trigger workflows only through policy gates.
- [ ] HUD clearly indicates active sensors and processing state.

## Likely files
`backend/app/sensorium/`, vision/audio adapters, companion camera, HUD, tests.
