# Architecture Boundaries

This document captures the current public boundary status for glassbox.

- 8 个命名边界中 6 个达 §4 护栏
- Platform 为 provisional / iOS-only structural provider
- CrawlPolicy 为 provisional
- 6/8 graduated + 2 provisional
- B-Q1 已决
- B-Q3 已决
- §10 待业务确认已清空
- Generic crawl policy 不算第二 app
- ARCHITECTURE_BOUNDARY_CONTRACT_VERSION = 2
- Effector plugins expose BackendCapabilities for coordinate space, connection
  requirements, transport labels, calibrated crop requirements, and wheel
  defaults.

The public tree keeps platform and crawl seams explicit while positioning the
runtime as iOS-first rather than as a finished cross-platform framework.
