# Fictional package and parts catalogue

These tasks and amounts are designed for this portfolio, not manufacturer schedules. Packages below contain only incremental work.

| Package | Task ID | Task | Required | Proposed parts |
|---|---|---|---|---|
| P1000 | BASIC | Complete the basic inspection checklist | Mandatory | Basic service consumables kit: 1 unit; Cleaning wipe: 2 unit |
| P1000 | FLUID-CHECK | Inspect fluid levels and record findings | Mandatory | None |
| P1000 | CONNECTION | Check connections and visible condition | Mandatory | None |
| P1000 | WASHER | Top up washer fluid if needed | Conditional | Washer fluid: 1 L |
| P5000 | OIL | Replace engine oil | Mandatory | Engine oil: capacity L |
| P5000 | FILTER | Replace oil filter and sealing washer | Mandatory | Oil filter: 1 unit; Sealing washer: 1 unit |
| P5000 | FINDINGS | Record lubrication inspection findings | Mandatory | None |
| P10000 | AIR | Replace engine air filter | Mandatory | Engine air filter: 1 unit |
| P10000 | PLUG | Replace spark-plug set | Mandatory | Spark-plug set: 1 set |
| P10000 | EXTENDED | Complete extended inspection checklist | Mandatory | Cleaning wipe: 3 unit |

`capacity` is the model oil amount:

| Model | Fictional model | Oil (L) |
|---|---|---|
| ALD | Alder Compact | 3.5 |
| BIR | Birch Sedan | 4.2 |
| CED | Cedar SUV | 5.6 |
| ELM | Elm Van | 6.3 |

At 10k, three packages yield ten unique tasks. Basic inspection uses two wipes; extended inspection uses three additional wipes: five total. This sums genuine consumption once per task, without repeating inherited packages. A 5k service uses seven tasks; 1k uses four. Only WASHER is conditional.

All part SKUs use `SP-{model}-{family}` and are accepted only for that order’s saved model catalogue. Liquids accept decimal amounts up to the proposal; required amounts must be met. `unit` and `set` require whole quantities. Washer fluid is up to 1 L only if needed.

## Example ALD combined 10,000-km proposal

| SKU | Part | Proposed | Mandatory | Unit |
|---|---|---|---|---|
| SP-ALD-AIR | Engine air filter | 1 | 1 | unit |
| SP-ALD-PLUG | Spark-plug set | 1 | 1 | set |
| SP-ALD-WIPE | Cleaning wipe | 5 | 5 | unit |
| SP-ALD-OIL | Engine oil | 3.5 | 3.5 | L |
| SP-ALD-FILTER | Oil filter | 1 | 1 | unit |
| SP-ALD-SEAL | Sealing washer | 1 | 1 | unit |
| SP-ALD-BASIC-KIT | Basic service consumables kit | 1 | 1 | unit |
| SP-ALD-WASHER | Washer fluid | 1 | 0 | L |
