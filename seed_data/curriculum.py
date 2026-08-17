"""Curriculum, staffing, fee and enrolment data for the seed population."""

CLASSES = [
    'Basic 1', 'Basic 2', 'Basic 3', 'Basic 4', 'Basic 5',
    'JSS1', 'JSS2', 'JSS3',
    'SS1',
    'SS2 Science', 'SS2 Arts', 'SS2 Commerce',
    'SS3 Science', 'SS3 Arts', 'SS3 Commerce',
]

PRIMARY_SUBJECTS = [
    'English Studies', 'Mathematics', 'Basic Science and Technology',
    'National Values Education', 'Cultural and Creative Arts',
    'Christian Religious Studies', 'History', 'Yoruba Language',
    'Computer Studies', 'Physical and Health Education',
]

JSS_SUBJECTS = [
    'English Studies', 'Mathematics', 'Basic Science', 'Basic Technology',
    'Business Studies', 'Civic Education', 'Social Studies',
    'Christian Religious Studies', 'Yoruba Language', 'Computer Studies',
    'Agricultural Science', 'Home Economics', 'Physical and Health Education',
]

SS1_SUBJECTS = [
    'English Language', 'Mathematics', 'Biology', 'Chemistry', 'Physics',
    'Economics', 'Government', 'Literature-in-English',
    'Christian Religious Studies', 'Yoruba Language', 'Geography',
    'Further Mathematics', 'Computer Science', 'Civic Education',
]

SCIENCE_TRACK = [
    'English Language', 'Mathematics', 'Biology', 'Chemistry', 'Physics',
    'Further Mathematics', 'Computer Science', 'Civic Education',
    'Christian Religious Studies', 'Yoruba Language',
]

ARTS_TRACK = [
    'English Language', 'Mathematics', 'Literature-in-English', 'Government',
    'Economics', 'History', 'Geography', 'Civic Education',
    'Christian Religious Studies', 'Yoruba Language',
]

COMMERCE_TRACK = [
    'English Language', 'Mathematics', 'Economics', 'Commerce', 'Accounting',
    'Government', 'Geography', 'Civic Education',
    'Christian Religious Studies', 'Yoruba Language',
]

CURRICULUM = {}
for name in CLASSES[:5]:
    CURRICULUM[name] = PRIMARY_SUBJECTS
for name in CLASSES[5:8]:
    CURRICULUM[name] = JSS_SUBJECTS
CURRICULUM['SS1'] = SS1_SUBJECTS
for name in ['SS2 Science', 'SS3 Science']:
    CURRICULUM[name] = SCIENCE_TRACK
for name in ['SS2 Arts', 'SS3 Arts']:
    CURRICULUM[name] = ARTS_TRACK
for name in ['SS2 Commerce', 'SS3 Commerce']:
    CURRICULUM[name] = COMMERCE_TRACK

FEE_TIERS = {
    'Basic 1': 25000, 'Basic 2': 25000, 'Basic 3': 27000,
    'Basic 4': 27000, 'Basic 5': 30000,
    'JSS1': 45000, 'JSS2': 45000, 'JSS3': 48000,
    'SS1': 70000,
    'SS2 Science': 75000, 'SS2 Arts': 75000, 'SS2 Commerce': 75000,
    'SS3 Science': 80000, 'SS3 Arts': 80000, 'SS3 Commerce': 80000,
}

STUDENT_COUNTS = {
    'Basic 1': 37, 'Basic 2': 37, 'Basic 3': 37,
    'Basic 4': 37, 'Basic 5': 37,
    'JSS1': 38, 'JSS2': 38, 'JSS3': 38,
    'SS1': 41,
    'SS2 Science': 10, 'SS2 Arts': 10, 'SS2 Commerce': 10,
    'SS3 Science': 10, 'SS3 Arts': 10, 'SS3 Commerce': 10,
}

assert sum(STUDENT_COUNTS.values()) == 400, sum(STUDENT_COUNTS.values())

DOB_RANGES = {
    'Basic 1': (2018, 2019), 'Basic 2': (2017, 2018), 'Basic 3': (2016, 2017),
    'Basic 4': (2015, 2016), 'Basic 5': (2014, 2015),
    'JSS1': (2012, 2014), 'JSS2': (2011, 2013), 'JSS3': (2010, 2012),
    'SS1': (2008, 2010),
    'SS2 Science': (2007, 2009), 'SS2 Arts': (2007, 2009),
    'SS2 Commerce': (2007, 2009),
    'SS3 Science': (2006, 2008), 'SS3 Arts': (2006, 2008),
    'SS3 Commerce': (2006, 2008),
}

TEACHERS = [
    ('Adaeze', 'Okonkwo', 'Basic 1'),
    ('Emeka', 'Okafor', 'Basic 2'),
    ('Funke', 'Adeyemi', 'Basic 3'),
    ('Tunde', 'Bakare', 'Basic 4'),
    ('Ngozi', 'Eze', 'Basic 5'),
    ('Samuel', 'Adebayo', [('English Studies', c) for c in ['JSS1', 'JSS2', 'JSS3']]),
    ('Grace', 'Obi', [('Mathematics', c) for c in ['JSS1', 'JSS2', 'JSS3']]),
    ('Chinedu', 'Nwosu', [('Basic Science', c) for c in ['JSS1', 'JSS2', 'JSS3']]),
    ('Ibrahim', 'Musa', [('Basic Technology', c) for c in ['JSS1', 'JSS2', 'JSS3']]),
    ('Fatima', 'Bello', [('Business Studies', c) for c in ['JSS1', 'JSS2', 'JSS3']]),
    ('Kayode', 'Ogunleye', [('Civic Education', c) for c in ['JSS1', 'JSS2', 'JSS3']]
                      + [('Social Studies', c) for c in ['JSS1', 'JSS2', 'JSS3']]),
    ('Daniel', 'Umeh', [('Christian Religious Studies', c) for c in ['JSS1', 'JSS2', 'JSS3']]),
    ('Yemi', 'Alabi', [('Yoruba Language', c) for c in ['JSS1', 'JSS2', 'JSS3']]),
    ('Tobi', 'Adewale', [('Computer Studies', c) for c in ['JSS1', 'JSS2', 'JSS3']]),
    ('Chiamaka', 'Anya', [('Agricultural Science', c) for c in ['JSS1', 'JSS2', 'JSS3', 'SS1']]),
    ('Bola', 'Akinwunmi', [('Home Economics', c) for c in ['JSS1', 'JSS2', 'JSS3']]),
    ('Sarah', 'Eno', [('Physical and Health Education', c) for c in ['JSS1', 'JSS2', 'JSS3']]),
    ('Peter', 'Obiadi', [('English Language', c) for c in ['SS1', 'SS2 Science', 'SS2 Arts', 'SS2 Commerce']]),
    ('Helen', 'Ogundipe', [('English Language', c) for c in ['SS3 Science', 'SS3 Arts', 'SS3 Commerce']]),
    ('Femi', 'Ajayi', [('Mathematics', c) for c in ['SS1', 'SS2 Science', 'SS2 Arts', 'SS2 Commerce']]),
    ('Uche', 'Ibe', [('Mathematics', c) for c in ['SS3 Science', 'SS3 Arts', 'SS3 Commerce']]),
    ('Joseph', 'Adeleke', [('Biology', c) for c in ['SS1', 'SS2 Science', 'SS3 Science']]),
    ('Ronke', 'Oyelaran', [('Chemistry', c) for c in ['SS1', 'SS2 Science', 'SS3 Science']]),
    ('Dele', 'Osun', [('Physics', c) for c in ['SS1', 'SS2 Science', 'SS3 Science']]),
    ('Kola', 'Osho', [('Further Mathematics', c) for c in ['SS1', 'SS2 Science', 'SS3 Science']]),
    ('Amaka', 'Uzo', [('Economics', c) for c in ['SS1', 'SS2 Science', 'SS2 Arts', 'SS2 Commerce']]),
    ('Bayo', 'Fashola', [('Economics', c) for c in ['SS3 Science', 'SS3 Arts', 'SS3 Commerce']]),
    ('Chioma', 'Nnamdi', [('Commerce', c) for c in ['SS1', 'SS2 Commerce', 'SS3 Commerce']]),
    ('Segun', 'Balogun', [('Accounting', c) for c in ['SS2 Commerce', 'SS3 Commerce']]),
    ('Bose', 'Kuti', [('Government', c) for c in ['SS1', 'SS2 Science', 'SS2 Arts', 'SS2 Commerce']]
                + [('History', c) for c in ['SS2 Arts']]),
    ('Olu', 'Falade', [('Government', c) for c in ['SS3 Science', 'SS3 Arts', 'SS3 Commerce']]
                + [('History', c) for c in ['SS3 Arts']]),
    ('Rita', 'Okafor', [('Literature-in-English', c) for c in ['SS1', 'SS2 Arts', 'SS3 Arts']]),
    ('John', 'Adeosun', [('Christian Religious Studies', c) for c in ['SS1', 'SS2 Science', 'SS2 Arts', 'SS2 Commerce']]),
    ('Dorcas', 'Eri', [('Christian Religious Studies', c) for c in ['SS3 Science', 'SS3 Arts', 'SS3 Commerce']]),
    ('Wale', 'Ojo', [('Yoruba Language', c) for c in ['SS1', 'SS2 Science', 'SS2 Arts', 'SS2 Commerce']]),
    ('Bisi', 'Lawal', [('Yoruba Language', c) for c in ['SS3 Science', 'SS3 Arts', 'SS3 Commerce']]),
    ('Hamza', 'Suleiman', [('Geography', c) for c in ['SS1', 'SS2 Arts', 'SS2 Commerce', 'SS3 Arts', 'SS3 Commerce']]),
    ('Ify', 'Egbuna', [('Computer Science', c) for c in ['SS1', 'SS2 Science', 'SS3 Science']]),
    ('Lanre', 'Fagbemi', [('Civic Education', c) for c in ['SS1', 'SS2 Science', 'SS2 Arts', 'SS2 Commerce']]),
    ('Kemi', 'Adeola', [('Civic Education', c) for c in ['SS3 Science', 'SS3 Arts', 'SS3 Commerce']]),
]

MALE_NAMES = [
    'Chukwuemeka', 'Obinna', 'Ikenna', 'Tochukwu', 'Uchenna', 'Chinedu',
    'Emeka', 'Kelechi', 'Somto', 'Chibueze', 'Nnamdi', 'Onyekachi',
    'Adebayo', 'Tunde', 'Femi', 'Kunle', 'Segun', 'Oluwaseun', 'Ayodeji',
    'Damilola', 'Tobi', 'Oluwafemi', 'Babatunde', 'Wale', 'Kolawole',
    'Musa', 'Ibrahim', 'Abubakar', 'Suleiman', 'Abdullahi', 'Usman',
    'Hassan', 'Yusuf', 'Bello', 'Idris', 'Emmanuel', 'David', 'Daniel',
    'Joshua', 'Samuel', 'Michael', 'Peter', 'John', 'Joseph', 'Victor',
    'Blessing', 'Sunday', 'Festus', 'Godwin', 'Chima', 'Akin', 'Dare',
]

FEMALE_NAMES = [
    'Adaeze', 'Ngozi', 'Chiamaka', 'Amarachi', 'Chidinma', 'Ifeoma',
    'Nkechi', 'Ogechi', 'Chinenye', 'Uzoamaka', 'Ezinne', 'Kosisochukwu',
    'Funke', 'Yemi', 'Bisi', 'Ronke', 'Simisola', 'Temitope', 'Adesuwa',
    'Ayomide', 'Folake', 'Kemi', 'Bose', 'Modupe', 'Yetunde', 'Abike',
    'Aisha', 'Fatima', 'Amina', 'Hauwa', 'Zainab', 'Maryam', 'Safiya',
    'Rukaiya', 'Halima', 'Blessing', 'Esther', 'Ruth', 'Deborah',
    'Grace', 'Peace', 'Faith', 'Joy', 'Patience', 'Gloria', 'Precious',
    'Queen', 'Success', 'Victoria', 'Amara', 'Adaobi', 'Chioma',
]

SURNAMES = [
    'Okonkwo', 'Okafor', 'Nwosu', 'Eze', 'Obi', 'Umeh', 'Anya', 'Enyi',
    'Nnamdi', 'Onyeka', 'Ibe', 'Uzo', 'Eri', 'Egbuna', 'Obiadi', 'Ajayi',
    'Adeleke', 'Oyelaran', 'Osun', 'Osho', 'Balogun', 'Falade', 'Adeosun',
    'Adewale', 'Akinwunmi', 'Ogunleye', 'Adeyemi', 'Bakare', 'Alabi',
    'Ogundipe', 'Ojo', 'Lawal', 'Suleiman', 'Fagbemi', 'Adeola', 'Eno',
    'Bello', 'Musa', 'Ibrahim', 'Abubakar', 'Abdullahi', 'Usman', 'Hassan',
    'Yusuf', 'Idris', 'Adesina', 'Afolabi', 'Akanji', 'Akinola', 'Alao',
    'Adebayo', 'Adeleke', 'Adenuga', 'Adepoju', 'Adewale', 'Ajagbe',
    'Akinwale', 'Akinwumi', 'Akintola', 'Amaechi', 'Anyadike', 'Asoegwu',
    'Awosika', 'Chukwu', 'Dim', 'Ekwueme', 'Emeka', 'Enwere', 'Ezeilo',
    'Ezeugwu', 'Iheanacho', 'Ike', 'Ikegwu', 'Ilo', 'Imoh', 'Iwuchukwu',
    'Maduka', 'Mba', 'Nduka', 'Nwachukwu', 'Nwankwo', 'Nwafor', 'Nwogbo',
    'Obiagwu', 'Odoemelam', 'Ogunbiyi', 'Ojewale', 'Okeke', 'Okoro',
    'Okpara', 'Olowu', 'Omojola', 'Onwuchekwa', 'Oparah', 'Orji',
    'Osagie', 'Osuji', 'Ozoemena', 'Ugwu', 'Ukaegbu', 'Umeadi', 'Uzoma',
]