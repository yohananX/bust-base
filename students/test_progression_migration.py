from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class StudentProgressionMigrationTests(TransactionTestCase):
    migrate_from = ('students', '0011_classoffering_and_enrollment_offering')
    migrate_to = ('students', '0012_student_progression_phase3')

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])
        self.old_apps = self.executor.loader.project_state([self.migrate_from]).apps

    def tearDown(self):
        MigrationExecutor(connection).migrate([self.migrate_to])
        super().tearDown()

    def test_assigns_explicit_unclassified_stage_without_inferring_progression(self):
        School = self.old_apps.get_model('core', 'School')
        SchoolClass = self.old_apps.get_model('students', 'SchoolClass')
        school = School.objects.create(name='Legacy School', short_code='legacy-progression')
        first = SchoolClass.objects.create(
            school=school, name='Legacy A', academic_stage=None
        )
        second = SchoolClass.objects.create(
            school=school, name='Legacy B', academic_stage=None
        )

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        apps = executor.loader.project_state([self.migrate_to]).apps
        NewClass = apps.get_model('students', 'SchoolClass')
        AcademicStage = apps.get_model('students', 'AcademicStage')

        migrated = list(NewClass.objects.filter(pk__in=[first.pk, second.pk]))
        self.assertEqual(len(migrated), 2)
        self.assertTrue(all(item.academic_stage_id for item in migrated))
        self.assertEqual(
            {item.academic_stage_id for item in migrated},
            {migrated[0].academic_stage_id},
        )
        stage = AcademicStage.objects.get(pk=migrated[0].academic_stage_id)
        self.assertEqual(stage.name, 'Unclassified')
        self.assertFalse(stage.is_active)
        self.assertIsNone(stage.next_stage_id)
        self.assertTrue(all(item.next_class_id is None for item in migrated))
