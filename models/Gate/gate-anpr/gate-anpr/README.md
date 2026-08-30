# نظام تسجيل دخول وخروج السيارات باللوحات المصرية
# Egyptian Gate ANPR

يلتقط صورة كل سيارة تمر من البوابة، يقرأ رقم اللوحة العربية، ويسجّل:
**الوقت · رقم البوابة · دخول أم خروج · مسجّلة أم غير مسجّلة**، ويحسب مدة بقاء
كل سيارة بالداخل، وينبّه الحارس فورًا على أي سيارة غير مسجّلة أو محظورة.

Captures every vehicle at a gate, reads the Arabic plate, and logs
**time · gate number · entry/exit · known/unknown**, matches each exit to its
entry to compute stay duration, and alerts the guard on unknown or blacklisted
plates.

---

## ١ · التشغيل السريع / Quick start

**على ويندوز:** دبل كليك على **`START-GATE-ANPR`** — ملف واحد يفتح النظام
مباشرة في وضع التشغيل الفعلي. أدوات التركيب والصيانة في مجلد `tools`.

**على لينكس / Jetson:**

```bash
pip install -r requirements.txt

python run.py setup      # أول مرة فقط: الكاميرات والبوابات
python run.py check      # فحص
python run.py start      # التشغيل
```

`requirements.txt` خفيف (~٤٠ ميجابايت) ويكفي لتشغيل كل شيء ما عدا نموذج
التعرّف. نماذج الذكاء الاصطناعي تنزيل منفصل وكبير (عدة جيجابايت) لأن PyTorch
يأتي معها — ثبّتها لاحقاً فقط عندما تحتاجها فعلاً:

```bash
pip install -r requirements-ai.txt      # أو windows\6-install-ai.bat
```

ثم افتح المتصفح على `http://<ip-الجهاز>:8080`
Then open `http://<device-ip>:8080`.

`python tests/test_pipeline.py` يشغّل ١١٤ اختبارًا على النظام بدون أي كاميرا
ولا نموذج — طريقة سريعة للتأكد أن التثبيت سليم.

---

## ١.٥ · اختبار الكاميرا قبل أي شيء / test the camera first

```bash
python run.py camtest                    # كاميرا اللابتوب
python run.py camtest --source rtsp://admin:pass@192.168.1.64:554/Streaming/Channels/101
python run.py camtest --source config    # أول كاميرا في الإعدادات
```
على ويندوز: `windows\7-camera-test.bat`

يفتح `http://localhost:8090` ويعرض بث الكاميرا مع مربع حول كل لوحة، و**عرض
اللوحة بالبكسل** — وهو الرقم الذي يقرر نجاح التركيب:

| العرض | المعنى |
|---|---|
| ١٠٠ بكسل فأكثر | ✅ ممتاز |
| ٦٠–١٠٠ | ⚠️ مقبول بالكاد — قرّب الكاميرا |
| أقل من ٦٠ | ❌ القراءة ستفشل |

استخدمه أثناء تثبيت الكاميرا على البوابة: حرّك الكاميرا وراقب الرقم مباشرة حتى
يصير أخضر. هذه الخطوة توفّر أسابيع من محاولة إصلاح الدقة بالبرمجة لاحقاً.

النص المكتوب على الصورة بالحروف اللاتينية لأن OpenCV لا يرسم العربية — الرقم
العربي يظهر في اللوحة الجانبية.

---

## ١.٧ · مسح السجلات / clearing records

```bash
python run.py reset          # يمسح الحركة، ويُبقي السيارات المسجلة
python run.py reset --all    # يمسح السيارات المسجلة أيضًا
python run.py reset --all --snapshots --yes   # وكذلك الصور، بدون تأكيد
```

يعرض ما سيُحذف بالضبط ويطلب تأكيدًا.

---

## ٢ · تغيير الإعدادات / changing settings

**الطريقة الموصى بها — من المتصفح:** افتح `http://localhost:8080/settings`

من هناك تضيف كاميرا، تغيّر رقم بوابتها، تبدّل دخول/خروج، توقفها مؤقتًا، أو
تحذفها — والتغيير يُحفظ في `config/cameras.yaml` **ويعيد تشغيل الكاميرات
تلقائيًا** بدون إيقاف النظام.

الحقلان المميّزان بالأزرق هما اللذان يعطيان الكاميرا معناها:
**رقم البوابة** و**الاتجاه**.

نفس الصفحة تضبط: اسم الموقع، التنبيهات، البث المباشر، جمع الصور للتدريب،
عدد الإطارات المتفقة قبل التسجيل، وحدود الثقة.

**الطريقتان الأخريان:**

```bash
python run.py setup      # معالج تفاعلي — مناسب لأول تركيب
```

أو تعديل `config/cameras.yaml` بمحرر نصوص ثم إعادة التشغيل — انظر
`config/cameras.example.yaml`.

---

## ٢.٥ · معالج الإعداد الأول / first-time setup wizard

عند تشغيل `python run.py setup` يسأل النظام **عن كل كاميرا على حدة**:

```
★ رقم البوابة التي تراقبها هذه الكاميرا؟
★ Which GATE NUMBER does this camera watch?              [1]

★ هذه الكاميرا تصور السيارات الداخلة أم الخارجة؟
★ Does this camera see vehicles ENTERING or EXITING?
   1) دخول  / ENTRY
   2) خروج  / EXIT
   3) الاثنان / BOTH  (أقل دقة)
```

هذان الجوابان هما ما يعطي كل صورة معناها. أضف كاميرات بأي عدد — النظام يشغّل
لكل كاميرا خيطًا مستقلًا ويجمع كل النتائج في لوحة تحكم واحدة.

**نصيحة:** كاميرا للدخول وأخرى للخروج في كل بوابة. الكاميرا الواحدة للاتجاهين
تعمل، لكن تحديد الاتجاه يصبح تخمينًا من حجم اللوحة وهو أقل دقة.
*Two cameras per gate. One camera guessing direction from plate size is
noticeably less reliable.*

يمكن أيضًا تعديل `config/cameras.yaml` يدويًا — انظر
`config/cameras.example.yaml`.

---

## ٣ · لماذا اللوحات المصرية حالة خاصة / why Egyptian plates are hard

اللوحة المصرية = **حروف عربية + أرقام هندية**، بخط مختلف عن الخط المطبوع
العادي، وفوقها شريط ملوّن مكتوب عليه "مصر / EGYPT".

أي نظام ANPR جاهز مبني على الحروف اللاتينية سيفشل هنا. الأبحاث المنشورة على
اللوحات المصرية تصل كلها إلى نفس الاستنتاج: **عامل كل حرف كصنف مستقل في نموذج
كشف أجسام (YOLO) بدل استخدام OCR نصي عام** — الفارق حوالي ٩٩٪ مقابل ٩٤٪.

*A generic Latin-plate ANPR will not work. The published Egyptian ANPR work
consistently finds that per-character object detection beats general OCR by a
wide margin (~99% vs ~94%).*

لهذا النظام ثلاث خلفيات للقراءة، والتبديل بينها من سطر واحد في الإعدادات:

| الخلفية / backend | متى تستخدمها | الدقة المتوقعة |
|---|---|---|
| `yolo_chars` | الإنتاج — نموذج مدرّب على صورك أنت | الأعلى |
| `easyocr` | من اليوم الأول بدون تدريب | متوسطة |
| `stub` | الاختبارات فقط | — |

كما يزيل النظام الشريط الملوّن العلوي تلقائيًا قبل القراءة (بالتشبّع اللوني، لا
بنسبة ثابتة — فيعمل مع التاكسي البرتقالي والنقل الأحمر والحكومي الرمادي).

> **مجموعة الحروف:** المصادر العامة تختلف في القائمة الدقيقة للحروف المستخدمة
> على اللوحات المصرية. لذلك `anpr/plate_text.py` يحتوي على مجموعتين: واحدة
> واسعة للقراءة (لا نرفض أي قراءة)، وأخرى ضيقة تُستخدم في **ترجيح الثقة فقط**.
> عدّلها بحرية بعد أن ترى لوحات موقعك الفعلية.

---

## ٤ · الدقة: التصويت متعدد الإطارات / the accuracy trick

النظام **لا يثق أبدًا في إطار واحد**. لكل سيارة:

1. تُتتبَّع اللوحة عبر الإطارات وهي تقترب من البوابة.
2. كل إطار يعطي صوتًا موزونًا بـ (ثقة القراءة × منطقية اللوحة × حجم اللوحة).
3. القراءات المتشابهة (ه/٥ ، و/٦ ، ب/ت …) تُدمج بدل أن تفرّق الأصوات.
4. لا تُسجَّل السيارة إلا بعد اتفاق **٣ إطارات على الأقل**.
5. القراءة الضعيفة تُسجَّل مع علامة "تحتاج مراجعة" بدل أن تُرمى.

هذا هو ما يحوّل قارئًا دقته ٩٠٪ في الإطار الواحد إلى نظام يخطئ نادرًا.
*This is what turns a ~90%-per-frame reader into a system that is right almost
every time.* الكود في `anpr/tracker.py`.

---

## ٥ · ماذا يُسجَّل / what gets recorded

لكل مرور:

| الحقل | المحتوى |
|---|---|
| `ts` | التاريخ والوقت بتوقيت القاهرة |
| `gate_number` | رقم البوابة |
| `direction` | `entry` دخول / `exit` خروج |
| `plate` | رقم اللوحة بصيغة موحّدة |
| `status` | `known` مسجلة / `unknown` غير مسجلة / `blacklist` محظورة / `expired` تصريح منتهٍ |
| `confidence` | ثقة القراءة، وعدد الإطارات المتفقة |
| `snapshot` | صورة الإطار كاملًا + قصاصة اللوحة |

وجدول `visits` يربط كل خروج بدخوله ويحسب `duration_min` — يظهر في صفحة
التقارير: **من بالداخل الآن**، ومدة كل زيارة مكتملة.

قاعدة البيانات SQLite في `data/anpr.db` — ملف واحد، انسخه للنسخ الاحتياطي.

---

## ٦ · تسجيل السيارات في قاعدة البيانات / registering vehicles

ثلاث طرق، كلها من نفس الصفحة (`/vehicles`):

1. **استيراد Excel/CSV** — نزّل النموذج من الزر، املأه، ارفعه.
   الأعمدة: `plate, owner_name, phone, unit, category, car_make, car_color,
   valid_until, notes` — أو نفس الأسماء بالعربية (`رقم اللوحة`, `اسم المالك` …).
   الأرقام العربية والإنجليزية كلاهما مقبول؛ النظام يوحّدها.
   ```bash
   python tools/import_vehicles.py residents.xlsx --dry-run   # فحص أولًا
   python tools/import_vehicles.py residents.xlsx
   ```

2. **من الصورة الملتقطة** — أي سيارة غير مسجلة في السجل المباشر بجوارها زر
   **تسجيل**: يفتح النموذج ورقم اللوحة مملوء تلقائيًا من الصورة. هذه أسرع طريقة
   لبناء القاعدة في الأسبوع الأول.

3. **إدخال يدوي** — نموذج عادي.

**الفئات:** `resident` ساكن · `staff` موظف · `visitor` زائر · `vip` ·
`blacklist` محظور. الزائر يمكن إعطاؤه `valid_until` فينتهي تصريحه تلقائيًا.

---

## ٦.٥ · النماذج الجاهزة / the pretrained models

`models/*.pt` غير مرفوعة مع الكود (٨٠ ميجابايت). النماذج الحالية مأخوذة من
مشروع ACLPR (رخصة MIT) ومدرَّبة على مجموعة EALPR المصرية:

`models/*.pt` are gitignored (80 MB). The weights currently installed come from
the MIT-licensed [ACLPR project](https://github.com/AhmAshraf1/ACLPR), fine-tuned
on the Egyptian EALPR dataset. To reinstall them:

```bash
curl -L -o models/plate_detector.pt https://raw.githubusercontent.com/AhmAshraf1/ACLPR/main/models/yolo11m_car_plate_trained.pt
```

```bash
curl -L -o models/char_detector.pt https://raw.githubusercontent.com/AhmAshraf1/ACLPR/main/models/yolo11m_car_plate_ocr.pt
```

- `plate_detector.pt` — YOLOv11m, فئة واحدة `car_plate`.
- `char_detector.pt` — YOLOv11m، ٣٨ فئة: ١٠ أرقام + ٢٨ حرفًا عربيًا.

المهم: أسماء الفئات في نموذج الحروف مكتوبة بحروف لاتينية (`alif`، `baa`، `7aa`)
وليست حروفًا عربية. الترجمة موجودة في `CHAR_GLYPHS` داخل `anpr/ocr.py`، وأي
نموذج بديل يجب إما أن يتبع نفس الأسماء أو أن يُخرج حروفًا عربية مباشرة.

The character model's class names are Latin transliterations (`alif`, `baa`,
`7aa`), not Arabic glyphs. The mapping lives in `CHAR_GLYPHS` in `anpr/ocr.py`.
A replacement model must either follow the same naming or emit Arabic directly —
`_YoloCharReader` detects the latter and passes it through untouched.

## ٧ · تحسين الدقة على موقعك / getting it accurate at YOUR gate

هذه أهم فقرة في الملف.

**الأسبوع ١–٣ — اجمع فقط.** شغّل النظام عاديًا. كل قصاصة لوحة تُحفظ تلقائيًا في
`data/dataset/plates/<التاريخ>/` (الإعداد `collect_dataset: true`). لا تفعل شيئًا
آخر. صور من كاميرتك أنت، بزاويتك أنت، بإضاءتك وغبارك، تساوي أكثر من أي مجموعة
بيانات عامة.

**الأسبوع ٤ — راجِع.** النظام خمّن رقمًا لكل قصاصة، والتخمين غالبًا قريب:
```bash
python tools/label_helper.py --dir data/dataset/plates --no-show
# Enter = موافق ، أو اكتب التصحيح
```
هذا يحوّل "اكتب ٣٠٠٠ لوحة" إلى "اضغط Enter ٢٥٠٠ مرة وصحّح ٥٠٠".

**الأسبوع ٥ — درّب وانشر.**
```bash
python tools/train_char_detector.py --task chars --init    # ينشئ المجلدات
python tools/train_char_detector.py --task chars --data data/yolo/chars.yaml
# ينسخ النتيجة إلى models/char_detector.pt ويلتقطها النظام عند إعادة التشغيل
```

**لبدء التدريب قبل وصول بيانات الموقع** يمكن توليد لوحات صناعية:
```bash
python tools/make_test_plates.py --count 3000 --clean --labels \
    --out data/dataset/synthetic
```
البيانات الصناعية وحدها لا تكفي للإنتاج، لكنها تعطي نموذجًا يعمل في الأسبوع الأول.

---

## ٨ · التركيب على Jetson / Jetson deployment

```bash
sudo nvpmodel -m 0 && sudo jetson_clocks       # أقصى أداء

# لا تثبّت torch من pip على Jetson — استخدم عجلة JetPack من NVIDIA
pip install ultralytics --no-deps
pip install -r requirements.txt

# تحويل النموذج إلى TensorRT — أسرع ٣-٤ مرات
python tools/train_char_detector.py --export models/char_detector.pt
```

خدمة تعمل تلقائيًا عند الإقلاع:
```bash
sudo cp deploy/anpr.service /etc/systemd/system/
sudo systemctl enable --now anpr
journalctl -u anpr -f          # المتابعة الحية
```

**تركيب الكاميرا — يحدد الدقة أكثر من أي إعداد برمجي:**

| البند | التوصية |
|---|---|
| الزاوية الأفقية | أقل من ٣٠° عن محور السيارة |
| الزاوية الرأسية | أقل من ٣٠° (الارتفاع ≈ ١.٢–١.٦ م) |
| المسافة | ٣–٦ م من نقطة توقف السيارة |
| عرض اللوحة في الصورة | **١٠٠ بكسل على الأقل** — هذا هو الرقم الحاسم |
| الدقة | 1080p تكفي عند مسافة ٤ م بعدسة مناسبة |
| الليل | إضاءة IR إجبارية؛ أو كاميرا ANPR مخصصة بغالق سريع |
| الغالق | ١/٥٠٠ ث أو أسرع إن كانت السيارات لا تقف تمامًا |

اضبط `roi` في الإعدادات على المنطقة التي تتوقف فيها السيارة فقط — يقلل الحمل
على المعالج ويقلل القراءات الخاطئة من الشارع.

---

## ٩ · بنية المشروع / project layout

```
run.py                       نقطة التشغيل (setup / start / demo / check)
anpr/
  plate_text.py              توحيد اللوحات العربية، الترجمة، منطقية اللوحة
  config.py                  الكاميرات والبوابات والاتجاهات
  db.py                      SQLite: سيارات، أحداث، زيارات، تنبيهات
  detector.py                إيجاد اللوحة (YOLO أو كلاسيكي) + إزالة الشريط
  ocr.py                     قراءة الحروف (yolo_chars / easyocr / stub)
  tracker.py                 التتبع والتصويت متعدد الإطارات  ← قلب الدقة
  pipeline.py                خيط الكاميرا: إطار → حدث → تنبيه
  setup_wizard.py            معالج الإعداد (رقم البوابة + الاتجاه)
  web/                       لوحة التحكم العربية
tools/
  make_test_plates.py        مولّد لوحات مصرية صناعية
  label_helper.py            مراجعة سريعة للقصاصات المجمّعة
  train_char_detector.py     تدريب + تصدير TensorRT
  import_vehicles.py         استيراد Excel/CSV من الطرفية
tests/test_pipeline.py       ٩٢ اختبارًا، بدون كاميرا وبدون نماذج
```

---

## ١٠ · حدود النظام — كن صريحًا مع نفسك / honest limitations

* **بدون نموذج مدرّب، النظام يعمل لكن دقته منخفضة.** الكاشف الكلاسيكي و
  `easyocr` يكفيان لبدء جمع البيانات، لا للاعتماد عليهما في التشغيل الجاد.
  `python run.py check` سيحذّرك بوضوح إن لم يجد نموذجًا.
* **الليل بدون إضاءة IR = فشل.** لا يوجد حل برمجي لصورة غير موجودة.
* **اللوحات المتّسخة أو المثنية أو القديمة** ستُقرأ خطأ أحيانًا — لهذا توجد
  علامة "تحتاج مراجعة" وزر التصحيح في السجل.
* **مطابقة الدخول بالخروج** تفترض أن السيارة لا تخرج من بوابة غير مراقَبة. إن
  خرجت، تُغلق الزيارة القديمة تلقائيًا عند الدخول التالي.
* **لا يوجد تحكم في الحاجز** في هذه النسخة (لم تطلبه) — إضافته لاحقًا تحتاج
  كارت ريلاي فقط، ومكان الاستدعاء جاهز في `pipeline.py::_raise_alerts`.
* **لا يوجد تسجيل دخول للوحة التحكم.** ضعها على شبكة داخلية فقط. إن احتجت
  حسابات مستخدمين، هذه إضافة صغيرة.

---

## ١١ · الاختبارات / tests

```bash
python tests/test_pipeline.py
```

٩٢ اختبارًا تغطي: توحيد اللوحات العربية، التصويت متعدد الإطارات ورفض القراءة
الشاذة، منع التكرار، التصنيف (مسجلة/غير مسجلة/محظورة/منتهية)، مطابقة الدخول
بالخروج وحساب المدة، الاستيراد من Excel وCSV بأسماء أعمدة عربية، وكل صفحات
الويب. لا تحتاج كاميرا ولا نموذجًا ولا إنترنت.

---

## المصادر / sources

* [Vehicle registration plates of Egypt — Wikipedia](https://en.wikipedia.org/wiki/Vehicle_registration_plates_of_Egypt)
* [Egyptian car plate recognition based on YOLOv8, Easy-OCR, and CNN — JESIT](https://jesit.springeropen.com/articles/10.1186/s43067-024-00156-y)
* [Real-time Egyptian License Plate Detection and Recognition using YOLO — IJACSA](https://thesai.org/Publications/ViewPaper?Volume=13&Issue=7&Code=IJACSA&SerialNo=99)
* [Egyptian motorcycle and vehicle license plate recognition — Neural Computing and Applications](https://link.springer.com/article/10.1007/s00521-025-11302-6)
* [Edge AI-Based Real-Time ALPR Using YOLOv8 on NVIDIA Jetson Orin Nano — IEEE](https://ieeexplore.ieee.org/document/11469358/)
