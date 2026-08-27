# Plate reader evaluation - 2026-08-27

Dataset: `E:\VisionGuard\Egyptian Car Plates dataset\EALPR Vechicles dataset`
Truth: none (detection only)

**What this number is not.** This dataset is what the supplied models were trained on, so a score here measures whether our pipeline reproduces the source project on its own data - pipeline fidelity. It is not a prediction about the school's gate. Only site captures (`engine/tools/record.py`) or a hand test with real plates can answer that.

## Finding the plate

| Config | Images | Plates | Found | Missed | False | Recall | Precision |
|---|---|---|---|---|---|---|---|
| theirs | 2086 | 2142 | 2137 | 5 | 62 | 99.8% | 97.2% |
| fp32 | 2086 | 2142 | 2137 | 5 | 61 | 99.8% | 97.2% |
| fp16 | 2086 | 2142 | 2137 | 5 | 61 | 99.8% | 97.2% |
| trt | 2086 | 2142 | 2136 | 6 | 56 | 99.7% | 97.4% |

## Do the configurations read the same photo the same way?

Needs no ground truth. A tie between `theirs` and `fp32` means our port is faithful — not that either is right, which is a different question and the one the truth file answers.

| Pair | Compared | Agree | Rate |
|---|---|---|---|
| theirs vs fp32 | 2086 | 2086 | 100.0% |
| theirs vs fp16 | 2086 | 1946 | 93.3% |
| theirs vs trt | 2086 | 1532 | 73.4% |
| fp32 vs fp16 | 2086 | 1946 | 93.3% |
| fp32 vs trt | 2086 | 1532 | 73.4% |
| fp16 vs trt | 2086 | 1520 | 72.9% |

### Where theirs and fp16 differ

| Image | theirs | fp16 |
|---|---|---|
| 0002.jpg | 3 4 | 3 9 4 |
| 0005.jpg | T 843 | T 8432 |
| 0036.jpg | K | K 43 |
| 0051.jpg | E B 1 | E R B 1 |
| 0057.jpg | T S 829 | T S W 829 |
| 0065.jpg | E L Y 1 | E B Y 1 |
| 0076.jpg | N S 7 | N S R 7 |
| 0122.jpg | M W 6666 | M D W 6666 |
| 0138.jpg | 2 2 2 | 2 2 2 2 |
| 0143.jpg | H 385 | H 8 |
| 0199.jpg | 1 | G 1 |
| 0208.jpg | E 1 | 1 |
| 0231.jpg | 6 3 3 | M M 633 |
| 0235.jpg | 6 6 | 6 6 6 |
| 0253.jpg | C 2221 | 2 2 2 |
| 0264.jpg | D H B 5555 | H B 5555 |
| 0277.jpg | E 62 | 6 2 |
| 0291.jpg | H S L 111 | E S L 111 |
| 0297.jpg | A D M 111 | A M 111 |
| 0305.jpg | H A M 3366 | H A M 3363 |
| 0315.jpg | H T 1111 | T 1111 |
| 0365.jpg | 7 | A 7 |
| 0368.jpg | W E E 666 | E E 666 |
| 0384.jpg | B T L E 555 | B T L 5555 |
| 0411.jpg | M S 1111 | M S R 1111 |
| 0423.jpg | K M N 4444 | K M 4444 |
| 0432.jpg | 1 | A 1 |
| 0462.jpg | E E 9999 | G E 9999 |
| 0467.jpg | M C R 2222 | M C 2222 |
| 0468.jpg | B R 1 | B 1 |
| 0482.jpg | 5 5 5 5 | R M 5555 |
| 0495.jpg | M E M 4444 | M E M E 444 |
| 0504.jpg | 1 | H 1 |
| 0529.jpg | M S 1111 | M S R 1111 |
| 0543.jpg | 1 1 1 | S 111 |
| 0553.jpg | S Y F | S Y F 7 |
| 0554.jpg | E F 2 | E 2 |
| 0585.JPG | L E 217 | L N E 217 |
| 0587.JPG | L N E 217 | L E 217 |
| 0591.JPG | G G 8246 | G G B 8246 |
| ... | 100 more | |

### Where theirs and trt differ

| Image | theirs | trt |
|---|---|---|
| 0001.jpg | T N 7126 | S T N 7126 |
| 0002.jpg | 3 4 | 3 9 4 |
| 0004.jpg | 6 4 | S 6743 |
| 0005.jpg | T 843 | T 8432 |
| 0007.jpg | E M 5382 | E M A 5382 |
| 0008.jpg | E H 5 | E M H 35 |
| 0009.jpg | F | F E 7571 |
| 0010.jpg | G G 748 | K G 748 |
| 0012.jpg | M N 654 | M N 6254 |
| 0014.jpg | R Y 4851 | R W Y 4851 |
| 0017.jpg | B 4364 | B D 4364 |
| 0021.jpg | T R Y 164 | R Y E 1647 |
| 0024.jpg | 4 4 7 5 | E 4475 |
| 0035.jpg | S 513 | A S 513 |
| 0036.jpg | K | F K 9435 |
| 0042.jpg | 1 | A 1 |
| 0045.jpg | E 5 | E 55 |
| 0046.jpg | M H 6666 | M W H 6666 |
| 0050.jpg | 5 5 | A 55 |
| 0054.jpg | G L Y 888 | E L Y 888 |
| 0055.jpg | B K H E 5847 | K H E 5847 |
| 0057.jpg | T S 829 | T S W 829 |
| 0073.jpg | B W 6666 | B R W 6666 |
| 0075.jpg | 6 6 | 6 6 6 |
| 0077.jpg | A S 5555 | A S D 5555 |
| 0084.jpg | B D R 8888 | B D 8888 |
| 0097.jpg | E H 777 | E H 7777 |
| 0099.jpg | 7 7 7 | W W 7777 |
| 0103.jpg | E E E | S E E 5 |
| 0104.jpg | 1 | A 1 |
| 0105.jpg | 1 | M 1 |
| 0113.jpg | G M 6666 | N G M 6666 |
| 0116.jpg | 7 7 | A A A 7777 |
| 0118.jpg | L Y 999 | E L Y 9999 |
| 0122.jpg | M W 6666 | M D W 6666 |
| 0123.jpg | E 6666 | M E 6666 |
| 0125.jpg | 5 5 | 5 5 5 |
| 0130.jpg | (nothing) | 3 |
| 0135.jpg | D 5555 | G D 5555 |
| 0138.jpg | 2 2 2 | 2 2 2 2 |
| ... | 514 more | |

### Where fp32 and fp16 differ

| Image | fp32 | fp16 |
|---|---|---|
| 0002.jpg | 3 4 | 3 9 4 |
| 0005.jpg | T 843 | T 8432 |
| 0036.jpg | K | K 43 |
| 0051.jpg | E B 1 | E R B 1 |
| 0057.jpg | T S 829 | T S W 829 |
| 0065.jpg | E L Y 1 | E B Y 1 |
| 0076.jpg | N S 7 | N S R 7 |
| 0122.jpg | M W 6666 | M D W 6666 |
| 0138.jpg | 2 2 2 | 2 2 2 2 |
| 0143.jpg | H 385 | H 8 |
| 0199.jpg | 1 | G 1 |
| 0208.jpg | E 1 | 1 |
| 0231.jpg | 6 3 3 | M M 633 |
| 0235.jpg | 6 6 | 6 6 6 |
| 0253.jpg | C 2221 | 2 2 2 |
| 0264.jpg | D H B 5555 | H B 5555 |
| 0277.jpg | E 62 | 6 2 |
| 0291.jpg | H S L 111 | E S L 111 |
| 0297.jpg | A D M 111 | A M 111 |
| 0305.jpg | H A M 3366 | H A M 3363 |
| 0315.jpg | H T 1111 | T 1111 |
| 0365.jpg | 7 | A 7 |
| 0368.jpg | W E E 666 | E E 666 |
| 0384.jpg | B T L E 555 | B T L 5555 |
| 0411.jpg | M S 1111 | M S R 1111 |
| 0423.jpg | K M N 4444 | K M 4444 |
| 0432.jpg | 1 | A 1 |
| 0462.jpg | E E 9999 | G E 9999 |
| 0467.jpg | M C R 2222 | M C 2222 |
| 0468.jpg | B R 1 | B 1 |
| 0482.jpg | 5 5 5 5 | R M 5555 |
| 0495.jpg | M E M 4444 | M E M E 444 |
| 0504.jpg | 1 | H 1 |
| 0529.jpg | M S 1111 | M S R 1111 |
| 0543.jpg | 1 1 1 | S 111 |
| 0553.jpg | S Y F | S Y F 7 |
| 0554.jpg | E F 2 | E 2 |
| 0585.JPG | L E 217 | L N E 217 |
| 0587.JPG | L N E 217 | L E 217 |
| 0591.JPG | G G 8246 | G G B 8246 |
| ... | 100 more | |

### Where fp32 and trt differ

| Image | fp32 | trt |
|---|---|---|
| 0001.jpg | T N 7126 | S T N 7126 |
| 0002.jpg | 3 4 | 3 9 4 |
| 0004.jpg | 6 4 | S 6743 |
| 0005.jpg | T 843 | T 8432 |
| 0007.jpg | E M 5382 | E M A 5382 |
| 0008.jpg | E H 5 | E M H 35 |
| 0009.jpg | F | F E 7571 |
| 0010.jpg | G G 748 | K G 748 |
| 0012.jpg | M N 654 | M N 6254 |
| 0014.jpg | R Y 4851 | R W Y 4851 |
| 0017.jpg | B 4364 | B D 4364 |
| 0021.jpg | T R Y 164 | R Y E 1647 |
| 0024.jpg | 4 4 7 5 | E 4475 |
| 0035.jpg | S 513 | A S 513 |
| 0036.jpg | K | F K 9435 |
| 0042.jpg | 1 | A 1 |
| 0045.jpg | E 5 | E 55 |
| 0046.jpg | M H 6666 | M W H 6666 |
| 0050.jpg | 5 5 | A 55 |
| 0054.jpg | G L Y 888 | E L Y 888 |
| 0055.jpg | B K H E 5847 | K H E 5847 |
| 0057.jpg | T S 829 | T S W 829 |
| 0073.jpg | B W 6666 | B R W 6666 |
| 0075.jpg | 6 6 | 6 6 6 |
| 0077.jpg | A S 5555 | A S D 5555 |
| 0084.jpg | B D R 8888 | B D 8888 |
| 0097.jpg | E H 777 | E H 7777 |
| 0099.jpg | 7 7 7 | W W 7777 |
| 0103.jpg | E E E | S E E 5 |
| 0104.jpg | 1 | A 1 |
| 0105.jpg | 1 | M 1 |
| 0113.jpg | G M 6666 | N G M 6666 |
| 0116.jpg | 7 7 | A A A 7777 |
| 0118.jpg | L Y 999 | E L Y 9999 |
| 0122.jpg | M W 6666 | M D W 6666 |
| 0123.jpg | E 6666 | M E 6666 |
| 0125.jpg | 5 5 | 5 5 5 |
| 0130.jpg | (nothing) | 3 |
| 0135.jpg | D 5555 | G D 5555 |
| 0138.jpg | 2 2 2 | 2 2 2 2 |
| ... | 514 more | |

### Where fp16 and trt differ

| Image | fp16 | trt |
|---|---|---|
| 0001.jpg | T N 7126 | S T N 7126 |
| 0004.jpg | 6 4 | S 6743 |
| 0007.jpg | E M 5382 | E M A 5382 |
| 0008.jpg | E H 5 | E M H 35 |
| 0009.jpg | F | F E 7571 |
| 0010.jpg | G G 748 | K G 748 |
| 0012.jpg | M N 654 | M N 6254 |
| 0014.jpg | R Y 4851 | R W Y 4851 |
| 0017.jpg | B 4364 | B D 4364 |
| 0021.jpg | T R Y 164 | R Y E 1647 |
| 0024.jpg | 4 4 7 5 | E 4475 |
| 0035.jpg | S 513 | A S 513 |
| 0036.jpg | K 43 | F K 9435 |
| 0042.jpg | 1 | A 1 |
| 0045.jpg | E 5 | E 55 |
| 0046.jpg | M H 6666 | M W H 6666 |
| 0050.jpg | 5 5 | A 55 |
| 0051.jpg | E R B 1 | E B 1 |
| 0054.jpg | G L Y 888 | E L Y 888 |
| 0055.jpg | B K H E 5847 | K H E 5847 |
| 0065.jpg | E B Y 1 | E L Y 1 |
| 0073.jpg | B W 6666 | B R W 6666 |
| 0075.jpg | 6 6 | 6 6 6 |
| 0076.jpg | N S R 7 | N S 7 |
| 0077.jpg | A S 5555 | A S D 5555 |
| 0084.jpg | B D R 8888 | B D 8888 |
| 0097.jpg | E H 777 | E H 7777 |
| 0099.jpg | 7 7 7 | W W 7777 |
| 0103.jpg | E E E | S E E 5 |
| 0104.jpg | 1 | A 1 |
| 0105.jpg | 1 | M 1 |
| 0113.jpg | G M 6666 | N G M 6666 |
| 0116.jpg | 7 7 | A A A 7777 |
| 0118.jpg | L Y 999 | E L Y 9999 |
| 0123.jpg | E 6666 | M E 6666 |
| 0125.jpg | 5 5 | 5 5 5 |
| 0130.jpg | (nothing) | 3 |
| 0135.jpg | D 5555 | G D 5555 |
| 0139.jpg | M S 4444 | M S E E 44 |
| 0143.jpg | H 8 | G H 385 |
| ... | 526 more | |

## Reading the plate

Not measured: no confirmed-truth file. The dataset carries plate **boxes** only, so the 95% target needs `--label` first (task T014, and it needs the owner).
