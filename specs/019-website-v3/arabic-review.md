# Arabic review: sentences the site adds that are not in your design

Spec 019, P14-FR-023. Everything here was translated by Claude on 27 Sep 2026. **Nothing is published until you have read it.** Each Arabic line should say exactly what the English line says: no fact added, none dropped. Mark any line you want changed; the fix goes into `website/ar/…` (or `tools/build_website.mjs` / `website/main.js` for the short texts at the end).

The Arabic home page is not in this list, except the sentences in the last section. Its other words are your own design files (`VisionGuard Website v3 AR.dc.html` and `VisionGuard Mobile AR.dc.html`).

## About us (`website/ar/about.html`)

1. EN: COMPANY — ABOUT US
   AR: الشركة — من نحن

2. EN: About VisionGuard
   AR: عن VisionGuard

3. EN: VisionGuard turns the cameras a site already has into plain answers — who arrived, how busy an area is, where someone went — instead of hours of footage nobody has time to watch. It's built in Egypt for offices, factories, warehouses and hospitals that run their own cameras and want a straight answer, not another screen to babysit.
   AR: يحوّل VisionGuard الكاميرات الموجودة في موقعك إلى إجابات واضحة — من وصل، ومدى ازدحام مكانٍ ما، وإلى أين ذهب شخص — بدلًا من ساعات من التسجيلات لا يجد أحد وقتًا لمشاهدتها. صُنع في مصر للمكاتب والمصانع والمستودعات والمستشفيات التي تدير كاميراتها بنفسها وتريد إجابة مباشرة، لا شاشةً أخرى تحتاج إلى من يراقبها.

4. EN: Who it's for
   AR: لمن صُمّم

5. EN: VisionGuard is for the person who already has a wall of cameras and not enough hours to watch them: an office manager checking who's in, a factory floor keeping a restricted area clear, a warehouse watching who's near the loading bay, a hospital tracking who came and went. You don't replace your cameras or your team — you point VisionGuard at the feeds you already have and ask it what's happening.
   AR: VisionGuard مصمَّم لمن لديه بالفعل جدار من الكاميرات ولا يملك ساعات كافية لمشاهدتها: مدير مكتب يتحقق ممن حضر، وأرضية مصنع يجب أن تبقى فيها منطقة محظورة خالية، ومستودع يراقب من يقترب من رصيف التحميل، ومستشفى يتابع من جاء ومن غادر. لا تستبدل كاميراتك ولا فريقك — بل توجّه VisionGuard إلى البثّ الموجود لديك وتسأله عمّا يحدث.

6. EN: Honest by design
   AR: شفاف بطبيعته

7. EN: A camera system that guesses, or hides what it doesn't know, is worse than useless in a building full of people. VisionGuard is built around rules it does not break:
   AR: نظام كاميرات يخمّن، أو يُخفي ما لا يعرفه، أسوأ من عديم الفائدة في مبنى مليء بالناس. بُني VisionGuard حول قواعد لا يخرقها:

8. EN: A face names a person. Clothing only ever says "same body" — the two are never merged into one result. Green means confirmed by face, blue means matched by appearance, amber means not yet identified.
   AR: الوجه يحدّد هوية الشخص. أما الملابس فلا تقول إلا «الجسم نفسه» — ولا يُدمج الاثنان أبدًا في نتيجة واحدة. الأخضر يعني تأكيدًا بالوجه، والأزرق يعني مطابقة بالمظهر، والكهرماني يعني أن الشخص لم يُتعرَّف عليه بعد.

9. EN: If a camera, a model, or a connected service is offline, the screen says so, with the reason — never a stand-in answer.
   AR: إذا توقفت كاميرا أو نموذج أو خدمة متصلة، تقول الشاشة ذلك مع السبب — ولا تعرض إجابة بديلة أبدًا.

10. EN: Sample data is always labelled "demo." It only appears when you ask for it.
   AR: البيانات التجريبية تحمل دائمًا علامة «تجريبي»، ولا تظهر إلا عندما تطلبها.

11. EN: Every knife alert goes out marked unconfirmed until a person reviews it, and the entry — confirmed or false alarm — is never deleted from the history. The video behind it is kept for 30 days.
   AR: كل تنبيه سكين يُرسَل بعلامة «غير مؤكَّد» حتى يراجعه شخص، ولا يُحذف سجلّه من التاريخ أبدًا — سواء تأكّد أو كان إنذارًا كاذبًا. ويُحتفظ بالفيديو الخاص به 30 يومًا.

12. EN: Searching for a person, or asking a question, is logged before you see the result — who looked, and when.
   AR: البحث عن شخص، أو طرح سؤال، يُسجَّل قبل أن ترى النتيجة — من بحث، ومتى.

13. EN: Built to run at your site
   AR: مصمَّم ليعمل في موقعك

14. EN: VisionGuard runs on a computer at your own site, not as a cloud service watching your cameras from somewhere else. Camera footage and faces never leave the building. Add the cameras you already have by their address — nothing new to install at the camera end.
   AR: يعمل VisionGuard على جهاز كمبيوتر في موقعك أنت، لا كخدمة سحابية تراقب كاميراتك من مكان آخر. لا تغادر تسجيلات الكاميرات ولا الوجوه المبنى أبدًا. أضف الكاميرات الموجودة لديك بعناوينها — دون تركيب أي شيء جديد عند الكاميرا.

15. EN: Two things do leave the site. Alert emails go out through Gmail and carry facts only — what, where, when, how sure, who decided — never a name, a face or a picture. And when you type a question, the words — with names and plates masked into placeholders first — go to Google's Gemini, on its free tier, to work out what you're asking. Google's terms let them use what's submitted and let a human reviewer read it; we accepted that because masking cuts what leaves down to a sentence like "when did PERSON_1 arrive today?" A word the system doesn't recognise — a visitor's name is the usual case — is sent exactly as typed.
   AR: أمران فقط يغادران الموقع. رسائل التنبيه بالبريد الإلكتروني تُرسَل عبر Gmail وتحمل وقائع فقط — ماذا، وأين، ومتى، وبأي درجة يقين، ومن قرّر — ولا تحمل أبدًا اسمًا أو وجهًا أو صورة. وعندما تكتب سؤالًا، تُرسَل كلماته — بعد إخفاء الأسماء ولوحات السيارات واستبدالها برموز أولًا — إلى Gemini من Google، على باقته المجانية، لفهم ما تسأل عنه. تسمح شروط Google لها باستخدام ما يُرسَل إليها وبأن يقرأه مراجع بشري؛ وقد قبلنا ذلك لأن الإخفاء يقلّص ما يغادر الموقع إلى جملة مثل «متى وصل PERSON_1 اليوم؟». أما الكلمة التي لا يتعرّف عليها النظام — واسم الزائر هو الحالة المعتادة — فتُرسَل كما كُتبت تمامًا.

16. EN: Talk to us
   AR: تواصل معنا

17. EN: Want to see VisionGuard against your own cameras? Get in touch.
   AR: هل تريد أن ترى VisionGuard على كاميراتك أنت؟ تواصل معنا.

18. EN: Email: sales@vision-guard.org
   AR: البريد الإلكتروني: sales@vision-guard.org

19. EN: Phone & WhatsApp: +20 100 253 5081
   AR: الهاتف وواتساب: +20 100 253 5081

20. EN: Hours: Sunday–Thursday, 9:00–18:00
   AR: المواعيد: من الأحد إلى الخميس، من 9:00 إلى 18:00

21. EN: Last updated 27 September 2026
   AR: آخر تحديث: 27 سبتمبر 2026

## Security (`website/ar/security.html`)

> 28 Sep 2026: Security, Privacy policy and Terms of service are now one page, **Trust & privacy** (`website/ar/trust.html`). Its Arabic is the Arabic of the three old pages, shortened; the new sentences are listed at the end of this file. The old page below now forwards there.

1. EN: TRUST — SECURITY
   AR: الثقة — الأمان

2. EN: Security
   AR: الأمان

3. EN: VisionGuard runs on a computer inside your own building — not in a cloud account of ours. This page says, plainly, where what it sees is kept, who can use it, and the small number of things that ever leave the site.
   AR: يعمل VisionGuard على جهاز كمبيوتر داخل مبناك أنت — لا في حساب سحابي لدينا. توضّح هذه الصفحة بصراحة أين يُحفظ ما يراه، ومن يستطيع استخدامه، والأشياء القليلة التي قد تغادر الموقع.

4. EN: Where it's kept
   AR: أين تُحفظ البيانات

5. EN: Camera footage, face data and attendance are stored in local files on the machine at your site. Search history — every track-a-person search and every question asked through Ask — is written down too, but today that record lives only in the server's memory, not in a file; more on that below. Nothing about your site is copied anywhere else by default — only the two exceptions later on this page ever leave.
   AR: تُخزَّن تسجيلات الكاميرات وبيانات الوجوه والحضور في ملفات محلية على الجهاز الموجود في موقعك. ويُدوَّن سجل البحث أيضًا — كل بحث لتتبّع شخص وكل سؤال يُطرح عبر «اسأل» — لكن هذا السجل موجود اليوم في ذاكرة الخادم فقط، لا في ملف؛ والتفاصيل أدناه. لا يُنسخ أي شيء عن موقعك إلى أي مكان آخر افتراضيًا — والاستثناءان المذكوران لاحقًا في هذه الصفحة هما وحدهما ما يغادر.

6. EN: Signing in
   AR: تسجيل الدخول

7. EN: Every account signs in with an email and a password of at least 12 characters. Passwords are never stored as typed — they go through a slow, one-way hash built for exactly this, so a stolen database is not a stolen password list. A wrong password and an account that doesn't exist come back the same way, in the same time, so there's nothing for a stranger to learn by guessing.
   AR: يسجّل كل حساب دخوله ببريد إلكتروني وكلمة مرور لا تقل عن 12 حرفًا. لا تُخزَّن كلمات المرور أبدًا كما كُتبت — بل تمرّ عبر تجزئة بطيئة أحادية الاتجاه مصمَّمة لهذا الغرض تحديدًا، فسرقة قاعدة البيانات لا تعني سرقة قائمة بكلمات المرور. وكلمة المرور الخاطئة والحساب غير الموجود يُرَدّ عليهما بالطريقة نفسها وفي الوقت نفسه، فلا يجد الغريب شيئًا يتعلّمه من التخمين.

8. EN: Signing in issues a temporary pass rather than a permanent one: it can be cancelled immediately if a laptop is lost or someone leaves, and it expires automatically 12 hours after you sign in, whether or not it was used the whole time.
   AR: يمنحك تسجيل الدخول تصريحًا مؤقتًا لا دائمًا: يمكن إلغاؤه فورًا إذا فُقد حاسوب محمول أو غادر شخص ما، وتنتهي صلاحيته تلقائيًا بعد 12 ساعة من تسجيل الدخول، سواء استُخدم طوال الوقت أم لا.

9. EN: Two roles, decided by the server
   AR: دوران، يحدّدهما الخادم

10. EN: Every account is either an administrator or IT — there is no third tier. Administrators can enrol people, add or edit cameras, manage accounts, remove a person and change settings. IT accounts can do the everyday work — watch cameras, run searches, clear an alert — but not that. Which one you are is decided by VisionGuard's own server, on every request, from your account; it is never taken from what a screen happens to show, so editing a browser changes nothing about what it lets you do. Anyone who can reach the console can sign up for their own account with no invitation needed, but it is always an IT account, never an administrator one — the first administrator, and any after it, is created by a command run on the machine itself, which nobody can reach over the network.
   AR: كل حساب إمّا مسؤول (administrator) أو IT — ولا يوجد مستوى ثالث. يستطيع المسؤولون تسجيل الأشخاص، وإضافة الكاميرات أو تعديلها، وإدارة الحسابات، وإزالة شخص، وتغيير الإعدادات. أما حسابات IT فتقوم بالعمل اليومي — مشاهدة الكاميرات، وإجراء عمليات البحث، وإغلاق تنبيه — دون ما سبق. ويحدّد خادم VisionGuard نفسه دورك، في كل طلب، من حسابك؛ ولا يُؤخذ أبدًا مما تعرضه الشاشة، لذا فإن تعديل المتصفح لا يغيّر شيئًا مما يسمح لك به. يستطيع أي شخص يصل إلى لوحة التحكم أن ينشئ حسابًا لنفسه دون حاجة إلى دعوة، لكنه يكون دائمًا حساب IT وليس حساب مسؤول أبدًا — فالمسؤول الأول، وأي مسؤول بعده، يُنشأ بأمر يُشغَّل على الجهاز نفسه، ولا يستطيع أحد الوصول إليه عبر الشبكة.

11. EN: Every search is written down
   AR: كل بحث يُدوَّن

12. EN: A track-a-person search is logged before its result is shown, not after — so a search that finds nothing is still on the record. Knife-alert decisions, camera changes, alert-recipient changes and removing a person are all logged the same way: who did it, what they did, and when.
   AR: يُسجَّل البحث لتتبّع شخص قبل عرض نتيجته، لا بعده — فالبحث الذي لا يجد شيئًا يبقى في السجل أيضًا. وتُسجَّل بالطريقة نفسها قرارات تنبيهات السكين، وتغييرات الكاميرات، وتغييرات مستلمي التنبيهات، وإزالة شخص: من فعل ذلك، وماذا فعل، ومتى.

13. EN: The plain limit today: that log lives in the server's memory, so restarting it clears the history. A fix that saves every entry for good, and lets an administrator remove a mistaken one only by typing a reason — leaving a permanent note that it happened — has been specified and is being prepared.
   AR: الحدّ الواضح اليوم: هذا السجل موجود في ذاكرة الخادم، لذا فإن إعادة تشغيله تمحو التاريخ. وقد حُدِّد إصلاح يحفظ كل إدخال بشكل دائم، ولا يسمح للمسؤول بإزالة إدخال خاطئ إلا بعد كتابة السبب — مع ترك ملاحظة دائمة بأن ذلك حدث — ويجري الإعداد له.

14. EN: How long footage is kept
   AR: مدة الاحتفاظ بالتسجيلات

15. EN: Recorded clips are deleted automatically after a set number of days — 30, by default. The video goes; the record that something happened — when, on which camera, who reviewed it — is kept. A restricted-area camera works a little differently: it keeps only its three most recent clips, for the same reason — proof, without keeping video forever.
   AR: تُحذف المقاطع المسجَّلة تلقائيًا بعد عدد محدَّد من الأيام — 30 يومًا افتراضيًا. يذهب الفيديو، ويبقى السجل الذي يثبت أن شيئًا ما حدث — متى، وعلى أي كاميرا، ومن راجعه. وتعمل كاميرا المنطقة المحظورة بطريقة مختلفة قليلًا: فهي تحتفظ بآخر ثلاثة مقاطع لها فقط، للسبب نفسه — دليل، دون الاحتفاظ بالفيديو إلى الأبد.

16. EN: Removing a person
   AR: إزالة شخص

17. EN: Only an administrator can remove someone, and it's logged before it happens. Their face data and their entry in the directory are deleted at once — VisionGuard stops recognising them from the next camera frame, with no restart needed. Their past sightings stay in the system but are unreachable from any page. A way to erase those too has been decided on but is not yet built.
   AR: لا يستطيع إزالة أحد إلا المسؤول، ويُسجَّل ذلك قبل حدوثه. تُحذف بيانات وجهه وإدخاله في الدليل فورًا — ويتوقف VisionGuard عن التعرّف عليه من إطار الكاميرا التالي، دون حاجة إلى إعادة تشغيل. تبقى مشاهداته السابقة في النظام لكن لا يمكن الوصول إليها من أي صفحة. وقد تقرّرت طريقة لمحوها هي أيضًا، لكنها لم تُبنَ بعد.

18. EN: What leaves the site
   AR: ما الذي يغادر الموقع

19. EN: Two things about what happens on your site leave it, and only two. Ask sends your typed question to Google's Gemini, after masking names and number plates on your own machine first — a name becomes a placeholder before anything is sent. Gemini's free tier is what's configured today, and its terms let Google use what's submitted and let a human reviewer read it; a paid plan would turn that off with no change to the product. A word VisionGuard doesn't recognise is sent exactly as typed, which can include a name if that's what was typed into the question.
   AR: أمران فقط مما يحدث في موقعك يغادرانه، ولا شيء غيرهما. ترسل ميزة «اسأل» سؤالك المكتوب إلى Gemini من Google، بعد إخفاء الأسماء ولوحات السيارات على جهازك أولًا — فيصبح الاسم رمزًا قبل إرسال أي شيء. والباقة المجانية من Gemini هي المضبوطة اليوم، وتسمح شروطها لـ Google باستخدام ما يُرسَل وبأن يقرأه مراجع بشري؛ والانتقال إلى باقة مدفوعة يوقف ذلك دون أي تغيير في المنتج. أما الكلمة التي لا يتعرّف عليها VisionGuard فتُرسَل كما كُتبت تمامًا، وقد يكون ذلك اسمًا إن كان هو ما كُتب في السؤال.

20. EN: Email alerts go out through Gmail, so Google's mail servers see the text — but the text carries facts only: what happened, where, when, how sure, and who decided. It never carries a name, a face or a picture.
   AR: تُرسَل تنبيهات البريد الإلكتروني عبر Gmail، لذا ترى خوادم البريد لدى Google نصّها — لكن النص يحمل وقائع فقط: ماذا حدث، وأين، ومتى، وبأي درجة يقين، ومن قرّر. ولا يحمل أبدًا اسمًا أو وجهًا أو صورة.

21. EN: The console's own connection
   AR: اتصال لوحة التحكم نفسها

22. EN: Today the console is reached over a plain connection on your site's own network — HTTPS for it has been planned but is not switched on yet. Until it is, treat that network the way you would any system holding this kind of data.
   AR: اليوم يُوصَل إلى لوحة التحكم عبر اتصال عادي على شبكة موقعك الخاصة — وقد خُطِّط لتفعيل HTTPS لها لكنه لم يُفعَّل بعد. وحتى يُفعَّل، تعامَل مع تلك الشبكة كما تتعامل مع أي نظام يحمل هذا النوع من البيانات.

23. EN: Reporting a problem
   AR: الإبلاغ عن مشكلة

24. EN: Found a security problem, or think you have one? Tell us directly: support@vision-guard.org, or call or WhatsApp +20 100 253 5081, Sunday to Thursday, 9:00–18:00.
   AR: وجدت مشكلة أمنية، أو تظن أنك وجدت واحدة؟ أخبرنا مباشرةً: support@vision-guard.org، أو اتصل أو راسلنا على واتساب على +20 100 253 5081، من الأحد إلى الخميس، من 9:00 إلى 18:00.

25. EN: Last updated 27 September 2026
   AR: آخر تحديث: 27 سبتمبر 2026

## Help centre (`website/ar/help.html`)

1. EN: TRUST — HELP CENTRE
   AR: الثقة — مركز المساعدة

2. EN: Help Centre
   AR: مركز المساعدة

3. EN: Answers to what people ask before they buy VisionGuard, and after. Everything below matches how the product works today, including the parts that are not finished yet.
   AR: إجابات عمّا يسأل عنه الناس قبل شراء VisionGuard وبعده. كل ما يلي يطابق طريقة عمل المنتج اليوم، بما في ذلك الأجزاء التي لم تكتمل بعد.

4. EN: Ask us a question
   AR: اسألنا سؤالًا

5. EN: Write to the support team here and we’ll reply by email, Sunday to Thursday. Common questions are answered below.
   AR: اكتب إلى فريق الدعم هنا وسنردّ عليك بالبريد الإلكتروني، من الأحد إلى الخميس. والأسئلة الشائعة مُجاب عنها أدناه.

6. EN: Your name
   AR: اسمك

7. EN: Email
   AR: البريد الإلكتروني

8. EN: Topic
   AR: الموضوع

9. EN: Your question
   AR: سؤالك

10. EN: Send question
   AR: أرسل السؤال

11. EN: Your question was not sent. Please email support@vision-guard.org or call +20 100 253 5081.
   AR: لم يُرسَل سؤالك. من فضلك راسلنا على support@vision-guard.org أو اتصل على +20 100 253 5081.

12. EN: Your question goes to our support inbox through FormSubmit. We use it only to answer you.
   AR: يصل سؤالك إلى صندوق بريد الدعم لدينا عبر FormSubmit، ونستخدمه فقط للرد عليك.

13. EN: Thank you — question received.
   AR: شكرًا لك — استلمنا سؤالك.

14. EN: We’ll reply to the email address you gave.
   AR: سنردّ على عنوان البريد الإلكتروني الذي أدخلته.

15. EN: Ask another question
   AR: اسأل سؤالًا آخر

16. EN: Which cameras work, and how do I add one?
   AR: ما الكاميرات التي تعمل، وكيف أضيف واحدة؟

17. EN: VisionGuard works with the cameras and recorders you already have. An administrator adds a camera from the console by its address and turns on the features it needs — attendance, people counting, restricted zones, track a person, knife detection, lost bag, vehicle gate. It starts working without a restart.
   AR: يعمل VisionGuard مع الكاميرات وأجهزة التسجيل الموجودة لديك بالفعل. يضيف المسؤول الكاميرا من لوحة التحكم بعنوانها ويفعّل الميزات التي تحتاجها — الحضور، وعدّ الأشخاص، والمناطق المحظورة، وتتبّع شخص، واكتشاف السكاكين، والحقيبة المفقودة، وبوابة المركبات. وتبدأ العمل دون إعادة تشغيل.

18. EN: Searching your network automatically for cameras is not built yet — you add each one by its address.
   AR: البحث التلقائي في شبكتك عن الكاميرات غير مبني بعد — تضيف كل كاميرا بعنوانها.

19. EN: IP camera or RTSP stream, added by address
   AR: كاميرا IP أو بثّ RTSP، تُضاف بالعنوان

20. EN: Existing NVR or DVR recorder, added channel by channel — only the channels that actually answer get added
   AR: جهاز تسجيل NVR أو DVR موجود، يُضاف قناةً قناة — ولا تُضاف إلا القنوات التي تستجيب فعلًا

21. EN: A plain webcam, for a quick single-entrance setup
   AR: كاميرا ويب عادية، لإعداد سريع لمدخل واحد

22. EN: What languages can I ask in?
   AR: بأي لغات يمكنني أن أسأل؟

23. EN: Type your question the way you would say it — English, Arabic, Franco-Arabic (Arabic written in Latin letters), or a mix of these in one sentence. Ask always tells you what it understood before it answers.
   AR: اكتب سؤالك كما تقوله — بالإنجليزية، أو العربية، أو الفرانكو (العربية مكتوبة بحروف لاتينية)، أو بمزيج منها في جملة واحدة. وتخبرك «اسأل» دائمًا بما فهمته قبل أن تجيب.

24. EN: The Arabic-language screens themselves — the menus and labels — are still an internal draft being checked, so for now the console and app stay in English even when your question was not.
   AR: أما شاشات المنتج العربية نفسها — القوائم والتسميات — فما زالت مسودة داخلية قيد المراجعة، لذا تبقى لوحة التحكم والتطبيق بالإنجليزية حاليًا حتى لو لم يكن سؤالك بالإنجليزية.

25. EN: Is there a phone app?
   AR: هل يوجد تطبيق للهاتف؟

26. EN: Yes. It carries the same tools as the desktop console — a home summary, live cameras, attendance, tracking, the vehicle register — across five tabs: Home, Cameras, Tools, People and More. It is the same data and the same rules, laid out for a smaller screen.
   AR: نعم. يحمل الأدوات نفسها التي في لوحة التحكم على الكمبيوتر — ملخّص الصفحة الرئيسية، والكاميرات المباشرة، والحضور، والتتبّع، وسجل المركبات — موزّعة على خمس علامات تبويب: Home وCameras وTools وPeople وMore. إنها البيانات نفسها والقواعد نفسها، مرتّبة لشاشة أصغر.

27. EN: It has been checked screen by screen on a simulated phone display, in light and dark, English and Arabic. It has not yet been tried on a real phone in someone's hand, so things like the on-screen keyboard covering a form, or a live camera over mobile data, are still unconfirmed.
   AR: جرى فحصه شاشةً شاشة على شاشة هاتف محاكاة، بالوضعين الفاتح والداكن، بالإنجليزية والعربية. ولم يُجرَّب بعد على هاتف حقيقي في يد أحد، لذا فإن أمورًا مثل تغطية لوحة المفاتيح لنموذج ما، أو بثّ كاميرا مباشر عبر بيانات الهاتف، ما زالت غير مؤكَّدة.

28. EN: How do alerts reach me?
   AR: كيف تصلني التنبيهات؟

29. EN: By email, and inside the console or phone app under "Needs your attention," where a guard can acknowledge it. An administrator decides who is on the list and which alerts they get. A knife detection sends one email when the entry opens, marked as not yet confirmed by a person, and a second once someone has reviewed it. Every message carries facts only — what, where, when, how sure, and who decided — never a name, a face or a photo.
   AR: بالبريد الإلكتروني، وداخل لوحة التحكم أو تطبيق الهاتف تحت «Needs your attention» (يحتاج إلى انتباهك)، حيث يستطيع الحارس الإقرار بالتنبيه. ويحدّد المسؤول من في القائمة وأي التنبيهات يتلقّون. ويرسل اكتشاف السكين رسالة بريد واحدة عند فتح السجل، بعلامة «لم يؤكّده شخص بعد»، ورسالة ثانية بعد أن يراجعه أحد. وتحمل كل رسالة وقائع فقط — ماذا، وأين، ومتى، وبأي درجة يقين، ومن قرّر — ولا تحمل أبدًا اسمًا أو وجهًا أو صورة.

30. EN: WhatsApp and SMS alerts were tried and removed; email is what ships today. Arabic-speaking recipients currently get the English wording, since the Arabic version of alert messages has not been checked yet.
   AR: جُرّبت تنبيهات واتساب والرسائل النصية ثم أُزيلت؛ والبريد الإلكتروني هو ما يعمل اليوم. ويتلقّى المستلمون الناطقون بالعربية الصياغة الإنجليزية حاليًا، لأن النسخة العربية من رسائل التنبيه لم تُراجَع بعد.

31. EN: What happens when a camera goes offline?
   AR: ماذا يحدث عندما تنقطع كاميرا؟

32. EN: Its tile shows NO SIGNAL, and VisionGuard keeps trying to reconnect on its own — nobody needs to restart anything. Every other camera and feature keeps running. System Health lists which camera is down and why, instead of just looking fine while it is not.
   AR: يعرض مربّعها NO SIGNAL (لا توجد إشارة)، ويواصل VisionGuard محاولة إعادة الاتصال من تلقاء نفسه — دون حاجة إلى أن يعيد أحد تشغيل أي شيء. وتستمر كل الكاميرات والميزات الأخرى في العمل. وتعرض صفحة System Health (صحة النظام) الكاميرا المتوقفة وسبب توقفها، بدلًا من أن تبدو سليمة وهي ليست كذلك.

33. EN: How long is footage kept?
   AR: كم مدة الاحتفاظ بالتسجيلات؟

34. EN: It depends on the kind of record. Day-to-day sightings and attendance are logged as data, with no video attached. A restricted-zone entry keeps a video clip — each camera keeps its three most recent. A knife detection keeps its video for 30 days, but the entry itself, that it happened, when, and who reviewed it, stays in your history for good. A vehicle-gate pass keeps a photo and a close-up of the plate for 30 days, and the pass record is also kept for good.
   AR: يعتمد ذلك على نوع السجل. تُسجَّل المشاهدات اليومية والحضور كبيانات، دون فيديو مرفق. ويحتفظ دخول المنطقة المحظورة بمقطع فيديو — تحتفظ كل كاميرا بآخر ثلاثة مقاطع لها. ويحتفظ اكتشاف السكين بالفيديو الخاص به 30 يومًا، لكن السجل نفسه — أنه حدث، ومتى، ومن راجعه — يبقى في تاريخك بشكل دائم. ويحتفظ مرور مركبة من البوابة بصورة ولقطة مقرّبة للوحة لمدة 30 يومًا، ويُحفظ سجل المرور أيضًا بشكل دائم.

35. EN: Older footage played back through Track a person comes from your own recorder, so its retention is set by your recorder, not by VisionGuard.
   AR: أما التسجيلات الأقدم التي تُعرض عبر «تتبّع شخص» فتأتي من جهاز التسجيل الخاص بك، لذا يحدّد جهاز التسجيل مدة الاحتفاظ بها، لا VisionGuard.

36. EN: Can a person be removed?
   AR: هل يمكن إزالة شخص؟

37. EN: Yes. An administrator can remove someone from People: their face data and profile are deleted and they stop being recognised immediately, with no restart needed, and the removal is logged first. Sightings recorded before the removal stay in the database, not visible on any page, until a full erasure feature, planned but not yet built, clears them completely.
   AR: نعم. يستطيع المسؤول إزالة شخص من صفحة People: تُحذف بيانات وجهه وملفّه، ويتوقف التعرّف عليه فورًا دون حاجة إلى إعادة تشغيل، وتُسجَّل الإزالة أولًا. أما المشاهدات المسجَّلة قبل الإزالة فتبقى في قاعدة البيانات، غير ظاهرة في أي صفحة، حتى تمحوها تمامًا ميزة محو كاملة مخطَّط لها لكنها لم تُبنَ بعد.

38. EN: Does anything I type ever leave the site?
   AR: هل يغادر الموقعَ أيُّ شيء أكتبه؟

39. EN: Camera footage and recognition run on a computer at your own site and stay there. Alert emails go out through Gmail with facts only, never a name, a face or a picture. And there is Ask: before your question goes anywhere, VisionGuard masks names and number plates on site, then sends the masked question to Google's Gemini, its free tier, to work out what you are asking. Gemini's terms let Google make use of what is submitted, and let human reviewers read it. A word Ask does not recognise, occasionally someone's name, is sent as typed; administrators can see exactly what was sent for any question.
   AR: تعمل تسجيلات الكاميرات والتعرّف على جهاز كمبيوتر في موقعك أنت وتبقى هناك. وتُرسَل رسائل التنبيه عبر Gmail بوقائع فقط، ولا تحمل أبدًا اسمًا أو وجهًا أو صورة. ثم هناك «اسأل»: قبل أن يذهب سؤالك إلى أي مكان، يُخفي VisionGuard الأسماء ولوحات السيارات داخل الموقع، ثم يرسل السؤال بعد الإخفاء إلى Gemini من Google، على باقته المجانية، لفهم ما تسأل عنه. وتسمح شروط Gemini لـ Google باستخدام ما يُرسَل، وبأن يقرأه مراجعون بشريون. أما الكلمة التي لا تتعرّف عليها «اسأل» — وأحيانًا تكون اسم شخص — فتُرسَل كما كُتبت؛ ويستطيع المسؤولون أن يروا بالضبط ما أُرسل لأي سؤال.

40. EN: What doesn't VisionGuard do yet?
   AR: ما الذي لا يفعله VisionGuard بعد؟

41. EN: People counting works today but is not accurate yet. On a recorded test, one person alone in view was read as anywhere from one to seven, averaging around two and a half. Making it accurate is planned work, and we say so rather than hide it. Lost bag outlines a bag of the colour you pick, live, on the cameras you are watching, but keeps no history: nothing is recorded, so a bag taken before you opened the page cannot be found afterwards, and no alert is sent. And VisionGuard does not search your network for cameras on its own — you add each one by its address.
   AR: عدّ الأشخاص يعمل اليوم لكنه ليس دقيقًا بعد. ففي اختبار مسجَّل، قُرئ شخص واحد بمفرده أمام الكاميرا على أنه من واحد إلى سبعة، بمتوسط يقارب اثنين ونصفًا. وجعله دقيقًا عمل مخطَّط له، ونقول ذلك بدلًا من إخفائه. وتحدّد ميزة «الحقيبة المفقودة» حقيبةً باللون الذي تختاره، مباشرةً، على الكاميرات التي تشاهدها، لكنها لا تحتفظ بأي تاريخ: لا يُسجَّل شيء، لذا لا يمكن العثور لاحقًا على حقيبة أُخذت قبل أن تفتح الصفحة، ولا يُرسَل أي تنبيه. ولا يبحث VisionGuard في شبكتك عن الكاميرات من تلقاء نفسه — تضيف كل كاميرا بعنوانها.

42. EN: Still need help?
   AR: ما زلت تحتاج إلى مساعدة؟

43. EN: Reach the team directly.
   AR: تواصل مع الفريق مباشرةً.

44. EN: Email: support@vision-guard.org
   AR: البريد الإلكتروني: support@vision-guard.org

45. EN: Phone and WhatsApp: +20 100 253 5081
   AR: الهاتف وواتساب: +20 100 253 5081

46. EN: Hours: Sunday – Thursday, 9:00 – 18:00
   AR: المواعيد: من الأحد إلى الخميس، من 9:00 إلى 18:00

47. EN: For pricing or a walkthrough on your own cameras, write to sales@vision-guard.org — we don't list prices here.
   AR: للأسعار أو لجولة على كاميراتك أنت، راسلنا على sales@vision-guard.org — لا ننشر الأسعار هنا.

48. EN: Last updated 27 September 2026
   AR: آخر تحديث: 27 سبتمبر 2026

49. EN: placeholder: Your name
   AR: placeholder: اسمك

50. EN: placeholder: you@company.com
   AR: placeholder: you@company.com

51. EN: placeholder: Tell us what you need help with.
   AR: placeholder: أخبرنا بما تحتاج إلى مساعدة فيه.

## Short texts the site shows by itself

| Where | English | Arabic |
|---|---|---|
| Items with no page yet | Soon | قريبًا |
| Button while sending | Sending… | جارٍ الإرسال… |
| Empty required field | Please fill in this field. | من فضلك املأ هذا الحقل. |
| Bad email | Please enter an email address, like name@company.com. | من فضلك اكتب بريدًا إلكترونيًا صحيحًا، مثل name@company.com. |
| Contact form not sent | Your message was not sent. Please email sales@vision-guard.org or call +20 100 253 5081. | لم تُرسَل رسالتك. من فضلك راسلنا على sales@vision-guard.org أو اتصل على ‎+20 100 253 5081. |
| After a sent message | Send another message | أرسل رسالة أخرى |
| Home page description (search results) | AI vision for workplaces. Ask your cameras a question — in your own language — and get the answer, with footage when there is some. | رؤية ذكية لأماكن العمل. اسأل كاميراتك سؤالًا — بلغتك — واحصل على الإجابة، مع المقطع المصوَّر عندما يوجد. |
| Tab titles | About us / Security / Help Centre — VisionGuard | من نحن / الأمان / مركز المساعدة — VisionGuard |

## Home page: sentences that replace untrue claims (added 28 Sep 2026)

These replace sentences in your Arabic home page design (converter edit E18), so they are
Claude's words, not yours. Each should say what the checked English says
(`specs/017-public-website/claims.md`). They are on PC and phone.

1. EN: With the clip when there is one.
   AR: مع المقطع المصوَّر عندما يوجد.

2. EN: …notices what matters and keeps a record.
   AR: …يلتقط ما يهم ويحتفظ بسجلّ له.

3. EN: Add each one by its address.
   AR: أضف كل كاميرا بعنوانها.

4. EN: Arrivals and sightings are logged. Zone and knife alerts keep the video.
   AR: الوصول والمشاهدات تُسجَّل، وتنبيهات المناطق والسكاكين تحتفظ بالفيديو.

5. EN: 500+ — cameras — the scale we're building for
   AR: كاميرا — الحجم الذي نسعى إليه

5a. EN: (console picture) All cameras up · across all cameras
    AR: كل الكاميرات تعمل · عبر كل الكاميرات

6. EN: 0 — made-up figures — every answer is real data
   AR: أرقام مختلَقة — كل إجابة من بيانات حقيقية

7. EN: How many, right now
   AR: كم عددهم، الآن

8. EN: Live headcounts for each area with a camera, …
   AR: عدد مباشر لكل منطقة فيها كاميرا، …

9. EN: Every alert says unconfirmed until a person reviews it.
   AR: كل تنبيه يقول «غير مؤكَّد» حتى يراجعه شخص.

10. EN: Pick a colour and see it outlined live on the cameras you choose.
    AR: اختر لونًا وشاهده محدَّدًا مباشرةً على الكاميرات التي تختارها.

11. EN: Follow someone across cameras, with evidence at every stop.
    AR: تتبّع شخصًا عبر الكاميرات، مع دليل عند كل محطة.

12. EN: Last seen (the hero's tracking card, PC only)
    AR: آخر ظهور

13. EN: Amber — not yet identified
    AR: الكهرماني — لم يُتعرَّف عليه بعد

14. EN: Ask in Arabic — Arabic screens in review
    AR: اسأل بالعربية — الشاشات العربية قيد المراجعة

15. EN: Searches and changes are logged, with who and when.
    AR: عمليات البحث والتغييرات مُسجَّلة، مع من قام بها ومتى.

16. EN: Audit trail — Every search is logged before results show.
    AR: سجل تدقيق — كل بحث يُسجَّل قبل أن تظهر نتائجه.

17. EN: Automatic retention — Footage is deleted after a set number of days.
    AR: حذف تلقائي — تُحذف اللقطات بعد عدد محدد من الأيام.

18. EN: Remove anyone — Their face data goes; recognition stops at once.
    AR: احذف أي شخص — تُحذف بيانات وجهه، ويتوقف التعرّف عليه فورًا.

19. EN: (footer) Ask your cameras a question — in your own language — and get the answer, with footage when there is some.
    AR: اسأل كاميراتك سؤالًا — بلغتك — واحصل على الإجابة، مع المقطع المصوَّر عندما يوجد.

## Trust & privacy: new sentences (added 28 Sep 2026)

Everything else on `website/ar/trust.html` is the old pages' Arabic, shortened.

1. EN: Trust & privacy  
   AR: الثقة والخصوصية

2. EN: TRUST (the small label above the title)  
   AR: الثقة

3. EN: How we protect what VisionGuard sees, what we do with your details, and the terms for using this site: the short version, with every point that matters.  
   AR: كيف نحمي ما يراه VisionGuard، وماذا نفعل ببياناتك، وشروط استخدام هذا الموقع: النسخة المختصرة، مع كل نقطة مهمة.

4. EN: (jump buttons) Security · Privacy · Terms  
   AR: الأمان · الخصوصية · الشروط

5. EN: On this page (read aloud by screen readers)  
   AR: في هذه الصفحة

6. EN: (the old addresses) This page is now part of Trust & privacy.  
   AR: أصبحت هذه الصفحة جزءًا من الثقة والخصوصية.

7. EN: (footer, Trust column) Trust & privacy  
   AR: الثقة والخصوصية

8. EN: (the Terms part's one-line introduction) The terms for using this site and its forms, what VisionGuard does and does not promise, and the law that applies.  
   AR: شروط استخدام هذا الموقع ونماذجه، وما يفعله VisionGuard وما لا يَعِد به، والقانون الذي يحكمها.
