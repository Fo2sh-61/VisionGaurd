# Model inventory

Generated 2026-08-22T11:38:20+00:00 by `engine/tools/audit_models.py`. Do not hand-edit — regenerate after adding or replacing a weight file.

20 files, 1.3 GB total.

## Summary

| File | Size | Format | Classes | Notes |
|---|---|---|---|---|
| `yolov8m-worldv2-school-960.engine` | 55.7 MB | tensorrt | 18 | GPU/TRT-locked — rebuild on target |
| `yolov8m-worldv2-search-960.engine` | 55.9 MB | tensorrt | 35 | GPU/TRT-locked — rebuild on target |
| `yolov8n-oiv7.engine` | 8.5 MB | tensorrt | 601 | GPU/TRT-locked — rebuild on target |
| `yolov8s-480.engine` | 22.9 MB | tensorrt | 80 | GPU/TRT-locked — rebuild on target |
| `yolov8s-pose-640.engine` | 24.2 MB | tensorrt | 1 | GPU/TRT-locked — rebuild on target |
| `face_detection_yunet_2023mar.onnx` | 227.1 KB | onnx | — |  |
| `face_recognition_sface_2021dec.onnx` | 36.9 MB | onnx | — |  |
| `yolov8m-worldv2-search.onnx` | 107.4 MB | onnx | 35 |  |
| `yolov8s-pose.onnx` | 44.6 MB | onnx | 1 |  |
| `yolov8s.onnx` | 42.8 MB | onnx | 80 |  |
| `bagbest.pt` | 54.5 MB | pytorch | 11 |  |
| `knifebest.pt` | 21.5 MB | pytorch | 1 |  |
| `yolo11m.pt` | 38.8 MB | pytorch | 80 |  |
| `yolov8m-worldv2-school.pt` | 343.2 MB | pytorch | 18 |  |
| `yolov8m-worldv2-search.pt` | 343.2 MB | pytorch | 35 |  |
| `yolov8m-worldv2.pt` | 54.6 MB | pytorch | 80 |  |
| `yolov8n-oiv7.pt` | 6.9 MB | pytorch | 601 |  |
| `yolov8s-pose.pt` | 22.4 MB | pytorch | 1 |  |
| `yolov8s.pt` | 21.5 MB | pytorch | 80 |  |
| `osnet_x1_0_market1501.pth` | 9.9 MB | pytorch-state-dict | — |  |

## Detail

### `yolov8m-worldv2-school-960.engine`

- **size** 55.7 MB (58,397,016 bytes)
- **modified** 2026-05-09T07:18:58+00:00
- **sha256 (first 64 MB)** `f9d9a6adc199089a`
- **format** tensorrt
- **build metadata** `{'description': 'Ultralytics YOLOv8m-worldv2 model ', 'author': 'Ultralytics', 'date': '2026-05-09T10:14:51.352059', 'version': '8.4.46', 'license': 'AGPL-3.0 License (https://ultralytics.com/license)', 'docs': 'https://docs.ultralytics.com', 'stride': 32, 'task': 'detect', 'batch': 1, 'imgsz': [960, 960], 'args': {'data': None, 'batch': 1, 'fraction': 1.0, 'half': True, 'int8': False, 'dynamic': False, 'simplify': True, 'nms': False}, 'channels': 3, 'end2end': False}`

<details><summary>18 classes</summary>

```
knife, kitchen knife, baseball bat, handgun, pistol, rifle, shotgun, machete, sword, dagger, pocket knife, box cutter, utility knife, razor blade, screwdriver, scissors, hammer, axe
```

</details>

### `yolov8m-worldv2-search-960.engine`

- **size** 55.9 MB (58,570,702 bytes)
- **modified** 2026-05-09T08:51:57+00:00
- **sha256 (first 64 MB)** `2c229e3151a96f0d`
- **format** tensorrt
- **build metadata** `{'description': 'Ultralytics YOLOv8m-worldv2 model ', 'author': 'Ultralytics', 'date': '2026-05-09T11:46:14.802723', 'version': '8.4.46', 'license': 'AGPL-3.0 License (https://ultralytics.com/license)', 'docs': 'https://docs.ultralytics.com', 'stride': 32, 'task': 'detect', 'batch': 1, 'imgsz': [960, 960], 'args': {'data': None, 'batch': 1, 'fraction': 1.0, 'half': True, 'int8': False, 'dynamic': False, 'simplify': True, 'nms': False}, 'channels': 3, 'end2end': False}`

<details><summary>35 classes</summary>

```
person, t-shirt, shorts, skirt, shoes, boots, sandals, cap, hat, helmet, hijab, glasses, shirt, sunglasses, mask, scarf, belt, tie, backpack, handbag, suitcase, umbrella, phone, jacket, bottle, book, laptop, cup, sports ball, coat, hoodie, sweater, vest, dress, pants
```

</details>

### `yolov8n-oiv7.engine`

- **size** 8.5 MB (8,917,027 bytes)
- **modified** 2026-05-06T08:32:06+00:00
- **sha256 (first 64 MB)** `6838e40c988b82f4`
- **format** tensorrt
- **build metadata** `{'description': 'Ultralytics YOLOv8n model trained on /usr/src/ultralytics/ultralytics/cfg/datasets/open-images-v7.yaml', 'author': 'Ultralytics', 'date': '2026-05-06T11:15:18.864022', 'version': '8.4.46', 'license': 'AGPL-3.0 License (https://ultralytics.com/license)', 'docs': 'https://docs.ultralytics.com', 'stride': 32, 'task': 'detect', 'batch': 1, 'imgsz': [640, 640], 'args': {'data': None, 'batch': 1, 'fraction': 1.0, 'half': True, 'int8': False, 'dynamic': False, 'simplify': True, 'nms': False}, 'channels': 3, 'end2end': False}`

<details><summary>601 classes</summary>

```
Accordion, Adhesive tape, Apple, Ceiling fan, Cello, Centipede, Chainsaw, Chair, Cheese, Cheetah, Chest of drawers, Chicken, Chime, Armadillo, Chisel, Chopsticks, Christmas tree, Clock, Closet, Clothing, Coat, Cocktail, Cocktail shaker, Coconut, Artichoke, Coffee, Coffee cup, Coffee table, Coffeemaker, Coin, Common fig, Common sunflower, Computer keyboard, Computer monitor, Computer mouse, Auto part, Container, Convenience store, Cookie, Cooking spray, Corded phone, Cosmetics, Couch, Countertop, Cowboy hat, Crab, Axe, Cream, Cricket ball, Crocodile, Croissant, Crown, Crutch, Cucumber, Cupboard, Curtain, Cutting board, Backpack, Dagger, Dairy Product, Deer, Desk, Dessert, Diaper, Dice, Digital clock, Dinosaur, Dishwasher, Bagel, Dog, Dog bed, Doll, Dolphin, Door, Door handle, Doughnut, Dragonfly, Drawer, Dress, Baked goods, Drill (Tool), Drink, Drinking straw, Drum, Duck, Dumbbell, Eagle, Earrings, Egg (Food), Elephant, Balance beam, Envelope, Eraser, Face powder, Facial tissue holder, Falcon, Fashion accessory, Fast food, Fax, Fedora, Filing cabinet, Ball, Fire hydrant, Fireplace, Fish, Flag, Flashlight, Flower, Flowerpot, Flute, Flying disc, Food, Aircraft, Balloon, Food processor, Football, Football helmet, Footwear, Fork, Fountain, Fox, French fries, French horn, Frog, Banana, Fruit, Frying pan, Furniture, Garden Asparagus, Gas stove, Giraffe, Girl, Glasses, Glove, Goat, Band-aid, Goggles, Goldfish, Golf ball, Golf cart, Gondola, Goose, Grape, Grapefruit, Grinder, Guacamole, Banjo, Guitar, Hair dryer, Hair spray, Hamburger, Hammer, Hamster, Hand dryer, Handbag, Handgun, Harbor seal, Barge, Harmonica, Harp, Harpsichord, Hat, Headphones, Heater, Hedgehog, Helicopter, Helmet, High heels, Barrel, Hiking equipment, Hippopotamus, Home appliance, Honeycomb, Horizontal bar, Horse, Hot dog, House, Houseplant, Human arm, Baseball bat, Human beard, Human body, Human ear, Human eye, Human face, Human foot, Human hair, Human hand, Human head, Human leg, Baseball glove, Human mouth, Human nose, Humidifier, Ice cream, Indoor rower, Infant bed, Insect, Invertebrate, Ipod, Isopod, Bat (Animal), Jacket, Jacuzzi, Jaguar (Animal), Jeans, Jellyfish, Jet ski, Jug, Juice, Kangaroo, Kettle, Bathroom accessory, Kitchen & dining room table, Kitchen appliance, Kitchen knife, Kitchen utensil, Kitchenware, Kite, Knife, Koala, Ladder, Ladle, Airplane, Bathroom cabinet, Ladybug, Lamp, Land vehicle, Lantern, Laptop, Lavender (Plant), Lemon, Leopard, Light bulb, Light switch, Bathtub, Lighthouse, Lily, Limousine, Lion, Lipstick, Lizard, Lobster, Loveseat, Luggage and bags, Lynx, Beaker, Magpie, Mammal, Man, Mango, Maple, Maracas, Marine invertebrates, Marine mammal, Measuring cup, Mechanical fan, Bear, Medical equipment, Microphone, Microwave oven, Milk, Miniskirt, Mirror, Missile, Mixer, Mixing bowl, Mobile phone, Bed, Monkey, Moths and butterflies, Motorcycle, Mouse, Muffin, Mug, Mule, Mushroom, Musical instrument, Musical keyboard, Bee, Nail (Construction), Necklace, Nightstand, Oboe, Office building, Office supplies, Orange, Organ (Musical Instrument), Ostrich, Otter, Beehive, Oven, Owl, Oyster, Paddle, Palm tree, Pancake, Panda, Paper cutter, Paper towel, Parachute, Beer, Parking meter, Parrot, Pasta, Pastry, Peach, Pear, Pen, Pencil case, Pencil sharpener, Penguin, Beetle, Perfume, Person, Personal care, Personal flotation device, Piano, Picnic basket, Picture frame, Pig, Pillow, Pineapple, Bell pepper, Pitcher (Container), Pizza, Pizza cutter, Plant, Plastic bag, Plate, Platter, Plumbing fixture, Polar bear, Pomegranate, Alarm clock, Belt, Popcorn, Porch, Porcupine, Poster, Potato, Power plugs and sockets, Pressure cooker, Pretzel, Printer, Pumpkin, Bench, Punching bag, Rabbit, Raccoon, Racket, Radish, Ratchet (Device), Raven, Rays and skates, Red panda, Refrigerator, Bicycle, Remote control, Reptile, Rhinoceros, Rifle, Ring binder, Rocket, Roller skates, Rose, Rugby ball, Ruler, Bicycle helmet, Salad, Salt and pepper shakers, Sandal, Sandwich, Saucer, Saxophone, Scale, Scarf, Scissors, Scoreboard, Bicycle wheel, Scorpion, Screwdriver, Sculpture, Sea lion, Sea turtle, Seafood, Seahorse, Seat belt, Segway, Serving tray, Bidet, Sewing machine, Shark, Sheep, Shelf, Shellfish, Shirt, Shorts, Shotgun, Shower, Shrimp, Billboard, Sink, Skateboard, Ski, Skirt, Skull, Skunk, Skyscraper, Slow cooker, Snack, Snail, Billiard table, Snake, Snowboard, Snowman, Snowmobile, Snowplow, Soap dispenser, Sock, Sofa bed, Sombrero, Sparrow, Binoculars, Spatula, Spice rack, Spider, Spoon, Sports equipment, Sports uniform, Squash (Plant), Squid, Squirrel, Stairs, Bird, Stapler, Starfish, Stationary bicycle, Stethoscope, Stool, Stop sign, Strawberry, Street light, Stretcher, Studio couch, Alpaca, Blender, Submarine, Submarine sandwich, Suit, Suitcase, Sun hat, Sunglasses, Surfboard, Sushi, Swan, Swim cap, Blue jay, Swimming pool, Swimwear, Sword, Syringe, Table, Table tennis racket, Tablet computer, Tableware, Taco, Tank, Boat, Tap, Tart, Taxi, Tea, Teapot, Teddy bear, Telephone, Television, Tennis ball, Tennis racket, Bomb, Tent, Tiara, Tick, Tie, Tiger, Tin can, Tire, Toaster, Toilet, Toilet paper, Book, Tomato, Tool, Toothbrush, Torch, Tortoise, Towel, Tower, Toy, Traffic light, Traffic sign, Bookcase, Train, Training bench, Treadmill, Tree, Tree house, Tripod, Trombone, Trousers, Truck, Trumpet, Boot, Turkey, Turtle, Umbrella, Unicycle, Van, Vase, Vegetable, Vehicle, Vehicle registration plate, Violin, Bottle, Volleyball (Ball), Waffle, Waffle iron, Wall clock, Wardrobe, Washing machine, Waste container, Watch, Watercraft, Watermelon, Bottle opener, Weapon, Whale, Wheel, Wheelchair, Whisk, Whiteboard, Willow, Window, Window blind, Wine, Bow and arrow, Wine glass, Wine rack, Winter melon, Wok, Woman, Wood-burning stove, Woodpecker, Worm, Wrench, Zebra, Ambulance, Bowl, Zucchini, Bowling equipment, Box, Boy, Brassiere, Bread, Briefcase, Broccoli, Bronze sculpture, Brown bear, Animal, Building, Bull, Burrito, Bus, Bust, Butterfly, Cabbage, Cabinetry, Cake, Cake stand, Ant, Calculator, Camel, Camera, Can opener, Canary, Candle, Candy, Cannon, Canoe, Cantaloupe, Antelope, Car, Carnivore, Carrot, Cart, Cassette deck, Castle, Cat, Cat furniture, Caterpillar, Cattle
```

</details>

### `yolov8s-480.engine`

- **size** 22.9 MB (23,990,034 bytes)
- **modified** 2026-05-14T06:11:49+00:00
- **sha256 (first 64 MB)** `c8e0ebea91bc77f8`
- **format** tensorrt
- **build metadata** `{'description': 'Ultralytics YOLOv8s model trained on coco.yaml', 'author': 'Ultralytics', 'date': '2026-05-14T09:06:49.896193', 'version': '8.4.46', 'license': 'AGPL-3.0 License (https://ultralytics.com/license)', 'docs': 'https://docs.ultralytics.com', 'stride': 32, 'task': 'detect', 'batch': 1, 'imgsz': [480, 480], 'args': {'data': None, 'batch': 1, 'fraction': 1.0, 'half': True, 'int8': False, 'dynamic': False, 'simplify': True, 'nms': False}, 'channels': 3, 'end2end': False}`

<details><summary>80 classes</summary>

```
person, bicycle, fire hydrant, stop sign, parking meter, bench, bird, cat, dog, horse, sheep, cow, car, elephant, bear, zebra, giraffe, backpack, umbrella, handbag, tie, suitcase, frisbee, motorcycle, skis, snowboard, sports ball, kite, baseball bat, baseball glove, skateboard, surfboard, tennis racket, bottle, airplane, wine glass, cup, fork, knife, spoon, bowl, banana, apple, sandwich, orange, bus, broccoli, carrot, hot dog, pizza, donut, cake, chair, couch, potted plant, bed, train, dining table, toilet, tv, laptop, mouse, remote, keyboard, cell phone, microwave, oven, truck, toaster, sink, refrigerator, book, clock, vase, scissors, teddy bear, hair drier, toothbrush, boat, traffic light
```

</details>

### `yolov8s-pose-640.engine`

- **size** 24.2 MB (25,392,542 bytes)
- **modified** 2026-05-09T10:35:11+00:00
- **sha256 (first 64 MB)** `f3f47311a9bbf57c`
- **format** tensorrt
- **build metadata** `{'description': 'Ultralytics YOLOv8s-pose model trained on /usr/src/app/ultralytics/datasets/coco-pose.yaml', 'author': 'Ultralytics', 'date': '2026-05-09T13:28:56.629325', 'version': '8.4.46', 'license': 'AGPL-3.0 License (https://ultralytics.com/license)', 'docs': 'https://docs.ultralytics.com', 'stride': 32, 'task': 'pose', 'batch': 1, 'imgsz': [640, 640], 'args': {'data': None, 'batch': 1, 'fraction': 1.0, 'half': True, 'int8': False, 'dynamic': False, 'simplify': True, 'nms': False}, 'channels': 3, 'end2end': False, 'kpt_shape': [17, 3]}`

<details><summary>1 classes</summary>

```
person
```

</details>

### `face_detection_yunet_2023mar.onnx`

- **size** 227.1 KB (232,589 bytes)
- **modified** 2026-04-26T16:19:52+00:00
- **sha256 (first 64 MB)** `8f2383e4dd3cfbb4`
- **format** onnx
- **inputs** `{'input': [1, 3, 640, 640]}`
- **outputs** `{'cls_8': [1, 6400, 1], 'cls_16': [1, 1600, 1], 'cls_32': [1, 400, 1], 'obj_8': [1, 6400, 1], 'obj_16': [1, 1600, 1], 'obj_32': [1, 400, 1], 'bbox_8': [1, 6400, 4], 'bbox_16': [1, 1600, 4], 'bbox_32': [1, 400, 4], 'kps_8': [1, 6400, 10], 'kps_16': [1, 1600, 10], 'kps_32': [1, 400, 10]}`

### `face_recognition_sface_2021dec.onnx`

- **size** 36.9 MB (38,696,353 bytes)
- **modified** 2026-04-26T16:24:52+00:00
- **sha256 (first 64 MB)** `0ba9fbfa01b5270c`
- **format** onnx
- **inputs** `{'data': [1, 3, 112, 112], 'scalar_op1': [1], 'scalar_op2': [1], 'conv_1_conv2d_weight': [32, 3, 3, 3], 'conv_1_batchnorm_gamma': [32], 'conv_1_batchnorm_beta': [32], 'conv_1_batchnorm_moving_mean': [32], 'conv_1_batchnorm_moving_var': [32], 'conv_1_relu_gamma': [32, 1, 1], 'conv_2_dw_conv2d_weight': [32, 1, 3, 3], 'conv_2_dw_batchnorm_gamma': [32], 'conv_2_dw_batchnorm_beta': [32], 'conv_2_dw_batchnorm_moving_mean': [32], 'conv_2_dw_batchnorm_moving_var': [32], 'conv_2_dw_relu_gamma': [32, 1, 1], 'conv_2_conv2d_weight': [64, 32, 1, 1], 'conv_2_batchnorm_gamma': [64], 'conv_2_batchnorm_beta': [64], 'conv_2_batchnorm_moving_mean': [64], 'conv_2_batchnorm_moving_var': [64], 'conv_2_relu_gamma': [64, 1, 1], 'conv_3_dw_conv2d_weight': [64, 1, 3, 3], 'conv_3_dw_batchnorm_gamma': [64], 'conv_3_dw_batchnorm_beta': [64], 'conv_3_dw_batchnorm_moving_mean': [64], 'conv_3_dw_batchnorm_moving_var': [64], 'conv_3_dw_relu_gamma': [64, 1, 1], 'conv_3_conv2d_weight': [128, 64, 1, 1], 'conv_3_batchnorm_gamma': [128], 'conv_3_batchnorm_beta': [128], 'conv_3_batchnorm_moving_mean': [128], 'conv_3_batchnorm_moving_var': [128], 'conv_3_relu_gamma': [128, 1, 1], 'conv_4_dw_conv2d_weight': [128, 1, 3, 3], 'conv_4_dw_batchnorm_gamma': [128], 'conv_4_dw_batchnorm_beta': [128], 'conv_4_dw_batchnorm_moving_mean': [128], 'conv_4_dw_batchnorm_moving_var': [128], 'conv_4_dw_relu_gamma': [128, 1, 1], 'conv_4_conv2d_weight': [128, 128, 1, 1], 'conv_4_batchnorm_gamma': [128], 'conv_4_batchnorm_beta': [128], 'conv_4_batchnorm_moving_mean': [128], 'conv_4_batchnorm_moving_var': [128], 'conv_4_relu_gamma': [128, 1, 1], 'conv_5_dw_conv2d_weight': [128, 1, 3, 3], 'conv_5_dw_batchnorm_gamma': [128], 'conv_5_dw_batchnorm_beta': [128], 'conv_5_dw_batchnorm_moving_mean': [128], 'conv_5_dw_batchnorm_moving_var': [128], 'conv_5_dw_relu_gamma': [128, 1, 1], 'conv_5_conv2d_weight': [256, 128, 1, 1], 'conv_5_batchnorm_gamma': [256], 'conv_5_batchnorm_beta': [256], 'conv_5_batchnorm_moving_mean': [256], 'conv_5_batchnorm_moving_var': [256], 'conv_5_relu_gamma': [256, 1, 1], 'conv_6_dw_conv2d_weight': [256, 1, 3, 3], 'conv_6_dw_batchnorm_gamma': [256], 'conv_6_dw_batchnorm_beta': [256], 'conv_6_dw_batchnorm_moving_mean': [256], 'conv_6_dw_batchnorm_moving_var': [256], 'conv_6_dw_relu_gamma': [256, 1, 1], 'conv_6_conv2d_weight': [256, 256, 1, 1], 'conv_6_batchnorm_gamma': [256], 'conv_6_batchnorm_beta': [256], 'conv_6_batchnorm_moving_mean': [256], 'conv_6_batchnorm_moving_var': [256], 'conv_6_relu_gamma': [256, 1, 1], 'conv_7_dw_conv2d_weight': [256, 1, 3, 3], 'conv_7_dw_batchnorm_gamma': [256], 'conv_7_dw_batchnorm_beta': [256], 'conv_7_dw_batchnorm_moving_mean': [256], 'conv_7_dw_batchnorm_moving_var': [256], 'conv_7_dw_relu_gamma': [256, 1, 1], 'conv_7_conv2d_weight': [512, 256, 1, 1], 'conv_7_batchnorm_gamma': [512], 'conv_7_batchnorm_beta': [512], 'conv_7_batchnorm_moving_mean': [512], 'conv_7_batchnorm_moving_var': [512], 'conv_7_relu_gamma': [512, 1, 1], 'conv_8_dw_conv2d_weight': [512, 1, 3, 3], 'conv_8_dw_batchnorm_gamma': [512], 'conv_8_dw_batchnorm_beta': [512], 'conv_8_dw_batchnorm_moving_mean': [512], 'conv_8_dw_batchnorm_moving_var': [512], 'conv_8_dw_relu_gamma': [512, 1, 1], 'conv_8_conv2d_weight': [512, 512, 1, 1], 'conv_8_batchnorm_gamma': [512], 'conv_8_batchnorm_beta': [512], 'conv_8_batchnorm_moving_mean': [512], 'conv_8_batchnorm_moving_var': [512], 'conv_8_relu_gamma': [512, 1, 1], 'conv_9_dw_conv2d_weight': [512, 1, 3, 3], 'conv_9_dw_batchnorm_gamma': [512], 'conv_9_dw_batchnorm_beta': [512], 'conv_9_dw_batchnorm_moving_mean': [512], 'conv_9_dw_batchnorm_moving_var': [512], 'conv_9_dw_relu_gamma': [512, 1, 1], 'conv_9_conv2d_weight': [512, 512, 1, 1], 'conv_9_batchnorm_gamma': [512], 'conv_9_batchnorm_beta': [512], 'conv_9_batchnorm_moving_mean': [512], 'conv_9_batchnorm_moving_var': [512], 'conv_9_relu_gamma': [512, 1, 1], 'conv_10_dw_conv2d_weight': [512, 1, 3, 3], 'conv_10_dw_batchnorm_gamma': [512], 'conv_10_dw_batchnorm_beta': [512], 'conv_10_dw_batchnorm_moving_mean': [512], 'conv_10_dw_batchnorm_moving_var': [512], 'conv_10_dw_relu_gamma': [512, 1, 1], 'conv_10_conv2d_weight': [512, 512, 1, 1], 'conv_10_batchnorm_gamma': [512], 'conv_10_batchnorm_beta': [512], 'conv_10_batchnorm_moving_mean': [512], 'conv_10_batchnorm_moving_var': [512], 'conv_10_relu_gamma': [512, 1, 1], 'conv_11_dw_conv2d_weight': [512, 1, 3, 3], 'conv_11_dw_batchnorm_gamma': [512], 'conv_11_dw_batchnorm_beta': [512], 'conv_11_dw_batchnorm_moving_mean': [512], 'conv_11_dw_batchnorm_moving_var': [512], 'conv_11_dw_relu_gamma': [512, 1, 1], 'conv_11_conv2d_weight': [512, 512, 1, 1], 'conv_11_batchnorm_gamma': [512], 'conv_11_batchnorm_beta': [512], 'conv_11_batchnorm_moving_mean': [512], 'conv_11_batchnorm_moving_var': [512], 'conv_11_relu_gamma': [512, 1, 1], 'conv_12_dw_conv2d_weight': [512, 1, 3, 3], 'conv_12_dw_batchnorm_gamma': [512], 'conv_12_dw_batchnorm_beta': [512], 'conv_12_dw_batchnorm_moving_mean': [512], 'conv_12_dw_batchnorm_moving_var': [512], 'conv_12_dw_relu_gamma': [512, 1, 1], 'conv_12_conv2d_weight': [512, 512, 1, 1], 'conv_12_batchnorm_gamma': [512], 'conv_12_batchnorm_beta': [512], 'conv_12_batchnorm_moving_mean': [512], 'conv_12_batchnorm_moving_var': [512], 'conv_12_relu_gamma': [512, 1, 1], 'conv_13_dw_conv2d_weight': [512, 1, 3, 3], 'conv_13_dw_batchnorm_gamma': [512], 'conv_13_dw_batchnorm_beta': [512], 'conv_13_dw_batchnorm_moving_mean': [512], 'conv_13_dw_batchnorm_moving_var': [512], 'conv_13_dw_relu_gamma': [512, 1, 1], 'conv_13_conv2d_weight': [1024, 512, 1, 1], 'conv_13_batchnorm_gamma': [1024], 'conv_13_batchnorm_beta': [1024], 'conv_13_batchnorm_moving_mean': [1024], 'conv_13_batchnorm_moving_var': [1024], 'conv_13_relu_gamma': [1024, 1, 1], 'conv_14_dw_conv2d_weight': [1024, 1, 3, 3], 'conv_14_dw_batchnorm_gamma': [1024], 'conv_14_dw_batchnorm_beta': [1024], 'conv_14_dw_batchnorm_moving_mean': [1024], 'conv_14_dw_batchnorm_moving_var': [1024], 'conv_14_dw_relu_gamma': [1024, 1, 1], 'conv_14_conv2d_weight': [1024, 1024, 1, 1], 'conv_14_batchnorm_gamma': [1024], 'conv_14_batchnorm_beta': [1024], 'conv_14_batchnorm_moving_mean': [1024], 'conv_14_batchnorm_moving_var': [1024], 'conv_14_relu_gamma': [1024, 1, 1], 'bn1_gamma': [1024], 'bn1_beta': [1024], 'bn1_moving_mean': [1024], 'bn1_moving_var': [1024], 'pre_fc1_weight': [128, 50176], 'pre_fc1_bias': [128], 'fc1_gamma': [128], 'fc1_beta': [128], 'fc1_moving_mean': [128], 'fc1_moving_var': [128]}`
- **outputs** `{'fc1': [1, 128]}`

### `yolov8m-worldv2-search.onnx`

- **size** 107.4 MB (112,661,630 bytes)
- **modified** 2026-05-09T08:46:18+00:00
- **sha256 (first 64 MB)** `ff23067f71a6ad44`
- **format** onnx
- **inputs** `{'images': [1, 3, 960, 960]}`
- **outputs** `{'output0': [1, 39, 18900]}`

<details><summary>35 classes</summary>

```
person, t-shirt, shirt, jacket, coat, hoodie, sweater, vest, dress, pants, shorts, skirt, shoes, boots, sandals, cap, hat, helmet, hijab, glasses, sunglasses, mask, scarf, belt, tie, backpack, handbag, suitcase, umbrella, phone, bottle, book, laptop, cup, sports ball
```

</details>

### `yolov8s-pose.onnx`

- **size** 44.6 MB (46,817,872 bytes)
- **modified** 2026-05-09T10:28:59+00:00
- **sha256 (first 64 MB)** `aea35bdc3c64721a`
- **format** onnx
- **inputs** `{'images': [1, 3, 640, 640]}`
- **outputs** `{'output0': [1, 56, 8400]}`

<details><summary>1 classes</summary>

```
person
```

</details>

### `yolov8s.onnx`

- **size** 42.8 MB (44,869,868 bytes)
- **modified** 2026-05-17T10:55:02+00:00
- **sha256 (first 64 MB)** `023c2e8ab435bdf4`
- **format** onnx
- **inputs** `{'images': [1, 3, 640, 640]}`
- **outputs** `{'output0': [1, 84, 8400]}`

<details><summary>80 classes</summary>

```
person, bicycle, car, motorcycle, airplane, bus, train, truck, boat, traffic light, fire hydrant, stop sign, parking meter, bench, bird, cat, dog, horse, sheep, cow, elephant, bear, zebra, giraffe, backpack, umbrella, handbag, tie, suitcase, frisbee, skis, snowboard, sports ball, kite, baseball bat, baseball glove, skateboard, surfboard, tennis racket, bottle, wine glass, cup, fork, knife, spoon, bowl, banana, apple, sandwich, orange, broccoli, carrot, hot dog, pizza, donut, cake, chair, couch, potted plant, bed, dining table, toilet, tv, laptop, mouse, remote, keyboard, cell phone, microwave, oven, toaster, sink, refrigerator, book, clock, vase, scissors, teddy bear, hair drier, toothbrush
```

</details>

### `bagbest.pt`

- **size** 54.5 MB (57,100,016 bytes)
- **modified** 2026-08-07T13:36:28+00:00
- **sha256 (first 64 MB)** `9b028e9dda6de471`
- **format** pytorch
- **architecture** WorldModel
- **parameters** 28,376,158
- **date** 2026-08-07T10:37:09.732716+00:00
- **version** 8.4.115
- **train args** `{'data': 'merged_dataset/data.yaml', 'epochs': '50', 'imgsz': '640', 'batch': '16', 'model': 'yolov8m-worldv2.pt', 'task': 'detect', 'mode': 'train', 'device': ''}`
- **train metrics** `{'metrics/precision(B)': 0.9013, 'metrics/recall(B)': 0.8174, 'metrics/mAP50(B)': 0.8936, 'metrics/mAP50-95(B)': 0.6888, 'val/box_loss': 0.9095, 'val/cls_loss': 0.6259, 'val/dfl_loss': 1.236, 'fitness': 0.6888}`
- **open-vocab buffers** `{'txt_feats': '(1, 11, 512)', 'clip_model': 'NoneType'}`

<details><summary>11 classes</summary>

```
backpack, laptop, jacket, key, handbag, suitcase, cup, book, shoes, cap, glasses
```

</details>

### `knifebest.pt`

- **size** 21.5 MB (22,516,010 bytes)
- **modified** 2026-08-22T08:27:12+00:00
- **sha256 (first 64 MB)** `92b4b241ff20b8bb`
- **format** pytorch
- **architecture** DetectionModel
- **parameters** 11,135,987
- **date** 2026-08-13T08:17:06.143441+00:00
- **version** 8.4.118
- **train args** `{'data': 'combined_knife_dataset/data.yaml', 'epochs': '80', 'imgsz': '640', 'batch': '16', 'model': '/content/drive/MyDrive/knife_training_v2/train/weights/best.pt', 'task': 'detect', 'mode': 'train', 'device': ''}`
- **train metrics** `{'metrics/precision(B)': 0.8652, 'metrics/recall(B)': 0.8592, 'metrics/mAP50(B)': 0.9217, 'metrics/mAP50-95(B)': 0.667, 'val/box_loss': 0.9453, 'val/cls_loss': 0.6534, 'val/dfl_loss': 1.2019, 'fitness': 0.667}`

<details><summary>1 classes</summary>

```
knife
```

</details>

### `yolo11m.pt`

- **size** 38.8 MB (40,684,120 bytes)
- **modified** 2026-05-03T21:55:54+00:00
- **sha256 (first 64 MB)** `d5ffc1a674953a08`
- **format** pytorch
- **architecture** DetectionModel
- **parameters** 20,114,688
- **date** 2024-09-25T21:10:31.135583
- **version** 8.2.100
- **train args** `{'data': '/ultralytics/ultralytics/cfg/datasets/coco.yaml', 'epochs': '600', 'imgsz': '640', 'batch': '128', 'model': 'yolo11m.yaml', 'task': 'detect', 'mode': 'train', 'device': '3'}`
- **train metrics** `{'metrics/precision(B)': 0.7378, 'metrics/recall(B)': 0.6169, 'metrics/mAP50(B)': 0.6844, 'metrics/mAP50-95(B)': 0.5144, 'val/box_loss': 0.9051, 'val/cls_loss': 0.864, 'val/dfl_loss': 1.0449, 'fitness': 0.9798, 'lr/pg0': 0.0001, 'lr/pg1': 0.0001, 'lr/pg2': 0.0001, 'train/seg_loss': 1.8583, 'train/cls_loss': 0.7547, 'train/dfl_loss': 1.0318, 'train/box_loss': 0.8688}`

<details><summary>80 classes</summary>

```
person, bicycle, car, motorcycle, airplane, bus, train, truck, boat, traffic light, fire hydrant, stop sign, parking meter, bench, bird, cat, dog, horse, sheep, cow, elephant, bear, zebra, giraffe, backpack, umbrella, handbag, tie, suitcase, frisbee, skis, snowboard, sports ball, kite, baseball bat, baseball glove, skateboard, surfboard, tennis racket, bottle, wine glass, cup, fork, knife, spoon, bowl, banana, apple, sandwich, orange, broccoli, carrot, hot dog, pizza, donut, cake, chair, couch, potted plant, bed, dining table, toilet, tv, laptop, mouse, remote, keyboard, cell phone, microwave, oven, toaster, sink, refrigerator, book, clock, vase, scissors, teddy bear, hair drier, toothbrush
```

</details>

### `yolov8m-worldv2-school.pt`

- **size** 343.2 MB (359,848,257 bytes)
- **modified** 2026-05-06T08:52:45+00:00
- **sha256 (first 64 MB)** `4450c1f6fe19e3af`
- **format** pytorch
- **architecture** WorldModel
- **date** 2026-05-06T11:52:44.839257
- **version** 8.4.46
- **train args** `{'epochs': '100', 'imgsz': '640', 'batch': '16', 'task': 'detect', 'mode': 'train'}`
- **open-vocab buffers** `{'txt_feats': '(1, 18, 512)', 'clip_model': 'CLIP'}`

<details><summary>18 classes</summary>

```
knife, kitchen knife, pocket knife, box cutter, utility knife, razor blade, screwdriver, scissors, hammer, axe, baseball bat, handgun, pistol, rifle, shotgun, machete, sword, dagger
```

</details>

### `yolov8m-worldv2-search.pt`

- **size** 343.2 MB (359,883,329 bytes)
- **modified** 2026-05-09T08:46:13+00:00
- **sha256 (first 64 MB)** `0d7e8a60c9d70764`
- **format** pytorch
- **architecture** WorldModel
- **date** 2026-05-09T11:46:12.972027
- **version** 8.4.46
- **train args** `{'epochs': '100', 'imgsz': '640', 'batch': '16', 'task': 'detect', 'mode': 'train'}`
- **open-vocab buffers** `{'txt_feats': '(1, 35, 512)', 'clip_model': 'CLIP'}`

<details><summary>35 classes</summary>

```
person, t-shirt, shirt, jacket, coat, hoodie, sweater, vest, dress, pants, shorts, skirt, shoes, boots, sandals, cap, hat, helmet, hijab, glasses, sunglasses, mask, scarf, belt, tie, backpack, handbag, suitcase, umbrella, phone, bottle, book, laptop, cup, sports ball
```

</details>

### `yolov8m-worldv2.pt`

- **size** 54.6 MB (57,233,192 bytes)
- **modified** 2026-05-06T08:49:17+00:00
- **sha256 (first 64 MB)** `b614d33aa35b8e61`
- **format** pytorch
- **architecture** WorldModel
- **parameters** 28,376,158
- **date** 2024-03-03T21:24:35.968940
- **version** 8.1.21
- **train args** `{'epochs': '100', 'imgsz': '640', 'batch': '16', 'task': 'detect', 'mode': 'train'}`
- **open-vocab buffers** `{'txt_feats': '(1, 80, 512)'}`

<details><summary>80 classes</summary>

```
person, bicycle, car, motorcycle, airplane, bus, train, truck, boat, traffic light, fire hydrant, stop sign, parking meter, bench, bird, cat, dog, horse, sheep, cow, elephant, bear, zebra, giraffe, backpack, umbrella, handbag, tie, suitcase, frisbee, skis, snowboard, sports ball, kite, baseball bat, baseball glove, skateboard, surfboard, tennis racket, bottle, wine glass, cup, fork, knife, spoon, bowl, banana, apple, sandwich, orange, broccoli, carrot, hot dog, pizza, donut, cake, chair, couch, potted plant, bed, dining table, toilet, tv, laptop, mouse, remote, keyboard, cell phone, microwave, oven, toaster, sink, refrigerator, book, clock, vase, scissors, teddy bear, hair drier, toothbrush
```

</details>

### `yolov8n-oiv7.pt`

- **size** 6.9 MB (7,226,939 bytes)
- **modified** 2026-05-03T13:43:29+00:00
- **sha256 (first 64 MB)** `3851dfbf39ed2a07`
- **format** pytorch
- **architecture** DetectionModel
- **parameters** 3,497,943
- **date** 2023-08-22T02:24:35.856041
- **version** 8.0.157
- **train args** `{'data': '/usr/src/ultralytics/ultralytics/cfg/datasets/open-images-v7.yaml', 'epochs': '50', 'imgsz': '640', 'batch': '128', 'model': 'yolov8n.yaml', 'task': 'detect', 'mode': 'train', 'device': '0'}`

<details><summary>601 classes</summary>

```
Accordion, Adhesive tape, Aircraft, Airplane, Alarm clock, Alpaca, Ambulance, Animal, Ant, Antelope, Apple, Armadillo, Artichoke, Auto part, Axe, Backpack, Bagel, Baked goods, Balance beam, Ball, Balloon, Banana, Band-aid, Banjo, Barge, Barrel, Baseball bat, Baseball glove, Bat (Animal), Bathroom accessory, Bathroom cabinet, Bathtub, Beaker, Bear, Bed, Bee, Beehive, Beer, Beetle, Bell pepper, Belt, Bench, Bicycle, Bicycle helmet, Bicycle wheel, Bidet, Billboard, Billiard table, Binoculars, Bird, Blender, Blue jay, Boat, Bomb, Book, Bookcase, Boot, Bottle, Bottle opener, Bow and arrow, Bowl, Bowling equipment, Box, Boy, Brassiere, Bread, Briefcase, Broccoli, Bronze sculpture, Brown bear, Building, Bull, Burrito, Bus, Bust, Butterfly, Cabbage, Cabinetry, Cake, Cake stand, Calculator, Camel, Camera, Can opener, Canary, Candle, Candy, Cannon, Canoe, Cantaloupe, Car, Carnivore, Carrot, Cart, Cassette deck, Castle, Cat, Cat furniture, Caterpillar, Cattle, Ceiling fan, Cello, Centipede, Chainsaw, Chair, Cheese, Cheetah, Chest of drawers, Chicken, Chime, Chisel, Chopsticks, Christmas tree, Clock, Closet, Clothing, Coat, Cocktail, Cocktail shaker, Coconut, Coffee, Coffee cup, Coffee table, Coffeemaker, Coin, Common fig, Common sunflower, Computer keyboard, Computer monitor, Computer mouse, Container, Convenience store, Cookie, Cooking spray, Corded phone, Cosmetics, Couch, Countertop, Cowboy hat, Crab, Cream, Cricket ball, Crocodile, Croissant, Crown, Crutch, Cucumber, Cupboard, Curtain, Cutting board, Dagger, Dairy Product, Deer, Desk, Dessert, Diaper, Dice, Digital clock, Dinosaur, Dishwasher, Dog, Dog bed, Doll, Dolphin, Door, Door handle, Doughnut, Dragonfly, Drawer, Dress, Drill (Tool), Drink, Drinking straw, Drum, Duck, Dumbbell, Eagle, Earrings, Egg (Food), Elephant, Envelope, Eraser, Face powder, Facial tissue holder, Falcon, Fashion accessory, Fast food, Fax, Fedora, Filing cabinet, Fire hydrant, Fireplace, Fish, Flag, Flashlight, Flower, Flowerpot, Flute, Flying disc, Food, Food processor, Football, Football helmet, Footwear, Fork, Fountain, Fox, French fries, French horn, Frog, Fruit, Frying pan, Furniture, Garden Asparagus, Gas stove, Giraffe, Girl, Glasses, Glove, Goat, Goggles, Goldfish, Golf ball, Golf cart, Gondola, Goose, Grape, Grapefruit, Grinder, Guacamole, Guitar, Hair dryer, Hair spray, Hamburger, Hammer, Hamster, Hand dryer, Handbag, Handgun, Harbor seal, Harmonica, Harp, Harpsichord, Hat, Headphones, Heater, Hedgehog, Helicopter, Helmet, High heels, Hiking equipment, Hippopotamus, Home appliance, Honeycomb, Horizontal bar, Horse, Hot dog, House, Houseplant, Human arm, Human beard, Human body, Human ear, Human eye, Human face, Human foot, Human hair, Human hand, Human head, Human leg, Human mouth, Human nose, Humidifier, Ice cream, Indoor rower, Infant bed, Insect, Invertebrate, Ipod, Isopod, Jacket, Jacuzzi, Jaguar (Animal), Jeans, Jellyfish, Jet ski, Jug, Juice, Kangaroo, Kettle, Kitchen & dining room table, Kitchen appliance, Kitchen knife, Kitchen utensil, Kitchenware, Kite, Knife, Koala, Ladder, Ladle, Ladybug, Lamp, Land vehicle, Lantern, Laptop, Lavender (Plant), Lemon, Leopard, Light bulb, Light switch, Lighthouse, Lily, Limousine, Lion, Lipstick, Lizard, Lobster, Loveseat, Luggage and bags, Lynx, Magpie, Mammal, Man, Mango, Maple, Maracas, Marine invertebrates, Marine mammal, Measuring cup, Mechanical fan, Medical equipment, Microphone, Microwave oven, Milk, Miniskirt, Mirror, Missile, Mixer, Mixing bowl, Mobile phone, Monkey, Moths and butterflies, Motorcycle, Mouse, Muffin, Mug, Mule, Mushroom, Musical instrument, Musical keyboard, Nail (Construction), Necklace, Nightstand, Oboe, Office building, Office supplies, Orange, Organ (Musical Instrument), Ostrich, Otter, Oven, Owl, Oyster, Paddle, Palm tree, Pancake, Panda, Paper cutter, Paper towel, Parachute, Parking meter, Parrot, Pasta, Pastry, Peach, Pear, Pen, Pencil case, Pencil sharpener, Penguin, Perfume, Person, Personal care, Personal flotation device, Piano, Picnic basket, Picture frame, Pig, Pillow, Pineapple, Pitcher (Container), Pizza, Pizza cutter, Plant, Plastic bag, Plate, Platter, Plumbing fixture, Polar bear, Pomegranate, Popcorn, Porch, Porcupine, Poster, Potato, Power plugs and sockets, Pressure cooker, Pretzel, Printer, Pumpkin, Punching bag, Rabbit, Raccoon, Racket, Radish, Ratchet (Device), Raven, Rays and skates, Red panda, Refrigerator, Remote control, Reptile, Rhinoceros, Rifle, Ring binder, Rocket, Roller skates, Rose, Rugby ball, Ruler, Salad, Salt and pepper shakers, Sandal, Sandwich, Saucer, Saxophone, Scale, Scarf, Scissors, Scoreboard, Scorpion, Screwdriver, Sculpture, Sea lion, Sea turtle, Seafood, Seahorse, Seat belt, Segway, Serving tray, Sewing machine, Shark, Sheep, Shelf, Shellfish, Shirt, Shorts, Shotgun, Shower, Shrimp, Sink, Skateboard, Ski, Skirt, Skull, Skunk, Skyscraper, Slow cooker, Snack, Snail, Snake, Snowboard, Snowman, Snowmobile, Snowplow, Soap dispenser, Sock, Sofa bed, Sombrero, Sparrow, Spatula, Spice rack, Spider, Spoon, Sports equipment, Sports uniform, Squash (Plant), Squid, Squirrel, Stairs, Stapler, Starfish, Stationary bicycle, Stethoscope, Stool, Stop sign, Strawberry, Street light, Stretcher, Studio couch, Submarine, Submarine sandwich, Suit, Suitcase, Sun hat, Sunglasses, Surfboard, Sushi, Swan, Swim cap, Swimming pool, Swimwear, Sword, Syringe, Table, Table tennis racket, Tablet computer, Tableware, Taco, Tank, Tap, Tart, Taxi, Tea, Teapot, Teddy bear, Telephone, Television, Tennis ball, Tennis racket, Tent, Tiara, Tick, Tie, Tiger, Tin can, Tire, Toaster, Toilet, Toilet paper, Tomato, Tool, Toothbrush, Torch, Tortoise, Towel, Tower, Toy, Traffic light, Traffic sign, Train, Training bench, Treadmill, Tree, Tree house, Tripod, Trombone, Trousers, Truck, Trumpet, Turkey, Turtle, Umbrella, Unicycle, Van, Vase, Vegetable, Vehicle, Vehicle registration plate, Violin, Volleyball (Ball), Waffle, Waffle iron, Wall clock, Wardrobe, Washing machine, Waste container, Watch, Watercraft, Watermelon, Weapon, Whale, Wheel, Wheelchair, Whisk, Whiteboard, Willow, Window, Window blind, Wine, Wine glass, Wine rack, Winter melon, Wok, Woman, Wood-burning stove, Woodpecker, Worm, Wrench, Zebra, Zucchini
```

</details>

### `yolov8s-pose.pt`

- **size** 22.4 MB (23,513,657 bytes)
- **modified** 2026-05-09T10:28:55+00:00
- **sha256 (first 64 MB)** `234314cd8baf6261`
- **format** pytorch
- **architecture** PoseModel
- **parameters** 11,626,046
- **date** 2023-04-17T17:23:30.278380
- **version** 8.0.77
- **train args** `{'data': '/usr/src/app/ultralytics/datasets/coco-pose.yaml', 'epochs': '1000', 'imgsz': '640', 'batch': '128', 'model': 'yolov8s-pose.yaml', 'task': 'pose', 'mode': 'train', 'device': '1'}`

<details><summary>1 classes</summary>

```
person
```

</details>

### `yolov8s.pt`

- **size** 21.5 MB (22,588,772 bytes)
- **modified** 2026-05-04T14:41:15+00:00
- **sha256 (first 64 MB)** `1f47a78bf100391c`
- **format** pytorch
- **architecture** DetectionModel
- **parameters** 11,166,560
- **date** 2022-12-30T08:15:10.989874
- **version** 8.0.0.dev0
- **train args** `{'data': 'coco.yaml', 'epochs': '500', 'imgsz': '640', 'batch': '16', 'model': 'yolov8s.yaml', 'task': 'detect', 'mode': 'train', 'device': '1'}`

<details><summary>80 classes</summary>

```
person, bicycle, car, motorcycle, airplane, bus, train, truck, boat, traffic light, fire hydrant, stop sign, parking meter, bench, bird, cat, dog, horse, sheep, cow, elephant, bear, zebra, giraffe, backpack, umbrella, handbag, tie, suitcase, frisbee, skis, snowboard, sports ball, kite, baseball bat, baseball glove, skateboard, surfboard, tennis racket, bottle, wine glass, cup, fork, knife, spoon, bowl, banana, apple, sandwich, orange, broccoli, carrot, hot dog, pizza, donut, cake, chair, couch, potted plant, bed, dining table, toilet, tv, laptop, mouse, remote, keyboard, cell phone, microwave, oven, toaster, sink, refrigerator, book, clock, vase, scissors, teddy bear, hair drier, toothbrush
```

</details>

### `osnet_x1_0_market1501.pth`

- **size** 9.9 MB (10,399,605 bytes)
- **modified** 2021-04-01T03:00:16+00:00
- **sha256 (first 64 MB)** `2809d3227f7d078f`
- **format** pytorch-state-dict
- **parameters** 2,577,891
- **classifier head** `(751, 512)`
