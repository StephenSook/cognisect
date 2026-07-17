# Third-party notices

Runtime and development dependencies retain their own licenses. The generated dependency-license manifest is the release source of truth and is checked in CI.

The application self-hosts these fonts through pinned Fontsource packages. Each font remains licensed under the SIL Open Font License 1.1; complete license text ships in its installed package:

- Lexend Variable — Copyright 2019 The Lexend Project Authors.
- Source Sans 3 Variable — Copyright Google Inc.
- JetBrains Mono Variable — Copyright 2020 The JetBrains Mono Project Authors.

Learner QR codes are generated locally with the pinned `qrcode` 1.5.4 package,
licensed under the MIT License. No learner capability is sent to an external QR
service.

The following research sources inform the product specification but are not bundled or relicensed:

- Vlassis (2004), *Making sense of the minus sign or becoming flexible in negativity*.
- Bofferding (2014), *Negative integer understanding: Characterizing first graders' mental models*.
- Maphosa (2017), *A Study of Errors and Misconceptions in the Learning of Addition and Subtraction of Directed Numbers in Grade 8*.
- MAP — Charting Student Math Misunderstandings competition data. Retrieval requires separate Kaggle rule acceptance; raw records are never committed.

No supplied private handoff, copied frontend source, restricted dataset record, or educator-review material is included in this repository.
