"""Generate the seed CSVs consumed by the data_import importer views.

Produces classes.csv, subjects.csv, staff.csv and students.csv (400 rows)
inside this directory. The CSVs match the importer column contracts:
- ClassImporter:   name, section
- SubjectImporter: class_name, subject_name
- StaffImporter:   first_name, last_name, username, email, phone_number, role
- StudentImporter: first_name, last_name, username, date_of_birth, gender,
                   class_name, parent_name, parent_email, parent_phone
"""
import csv
import os
import random

from curriculum import (
    CLASSES, CURRICULUM, DOB_RANGES, FEMALE_NAMES, MALE_NAMES,
    STUDENT_COUNTS, SURNAMES, TEACHERS,
)

HERE = os.path.dirname(os.path.abspath(__file__))
RNG = random.Random(2026)


def _username(first, last):
    base = '{}.{}'.format(first, last).lower().replace("'", '').replace('-', '')
    return base


def _phone():
    return '0803{}{:07d}'.format(RNG.randint(1, 9), RNG.randint(0, 9999999))


def _email(first, last):
    return '{}@gmail.com'.format(_username(first, last))


def write_classes():
    path = os.path.join(HERE, 'classes.csv')
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.writer(fh)
        writer.writerow(['name', 'section'])
        for name in CLASSES:
            section = 'Primary' if name.startswith('Basic') else (
                'Junior Secondary' if name.startswith('JSS') else 'Senior Secondary')
            writer.writerow([name, section])
    return path


def write_subjects():
    path = os.path.join(HERE, 'subjects.csv')
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.writer(fh)
        writer.writerow(['class_name', 'subject_name'])
        for class_name, subjects in CURRICULUM.items():
            for subject in subjects:
                writer.writerow([class_name, subject])
    return path


def write_staff():
    path = os.path.join(HERE, 'staff.csv')
    used = set()
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.writer(fh)
        writer.writerow(['first_name', 'last_name', 'username', 'email',
                         'phone_number', 'role'])
        for first, last, _ in TEACHERS:
            username = _username(first, last)
            n = 1
            while username in used:
                n += 1
                username = '{}{}'.format(_username(first, last), n)
            used.add(username)
            writer.writerow([first, last, username, _email(first, last),
                             _phone(), 'TEACHER'])
    return path


def write_students():
    path = os.path.join(HERE, 'students.csv')
    used = set()
    rows = []
    for class_name, count in STUDENT_COUNTS.items():
        low, high = DOB_RANGES[class_name]
        for _ in range(count):
            gender = 'FEMALE' if RNG.random() < 0.5 else 'MALE'
            first = RNG.choice(FEMALE_NAMES if gender == 'FEMALE' else MALE_NAMES)
            last = RNG.choice(SURNAMES)
            username = _username(first, last)
            n = 1
            while username in used:
                n += 1
                username = '{}{}'.format(_username(first, last), n)
            used.add(username)
            year = RNG.randint(low, high)
            month = RNG.randint(1, 12)
            day = RNG.randint(1, 28)
            dob = '{:04d}-{:02d}-{:02d}'.format(year, month, day)
            parent_prefix = 'Mr' if gender == 'MALE' else 'Mrs'
            parent_last = last
            rows.append([
                first, last, username, dob, gender, class_name,
                '{} {}'.format(parent_prefix, parent_last),
                _email('parent.{}'.format(username), parent_last),
                _phone(),
            ])
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.writer(fh)
        writer.writerow(['first_name', 'last_name', 'username', 'date_of_birth',
                         'gender', 'class_name', 'parent_name', 'parent_email',
                         'parent_phone'])
        writer.writerows(rows)
    return path


if __name__ == '__main__':
    print('classes.csv  ->', write_classes())
    print('subjects.csv ->', write_subjects())
    print('staff.csv    ->', write_staff())
    students = write_students()
    with open(students, encoding='utf-8') as fh:
        total = sum(1 for _ in csv.reader(fh)) - 1
    print('students.csv ->', students, '({} rows)'.format(total))