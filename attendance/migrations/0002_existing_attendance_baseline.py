from django.db import migrations


def snapshot_existing_records(apps, schema_editor):
    records = apps.get_model("analytics", "AttendanceRecord")
    entries = apps.get_model("attendance", "AttendanceAuditEntry")
    database = schema_editor.connection.alias
    # Historical actors and earlier values cannot be reconstructed. Label this
    # explicitly as a baseline rather than inventing an original marking event.
    batch = []
    for record in records.objects.using(database).all().iterator(chunk_size=1000):
        batch.append(
            entries(
                record_id=record.pk,
                action="BASELINE",
                old_status="",
                new_status=record.status,
            )
        )
        if len(batch) == 1000:
            entries.objects.using(database).bulk_create(batch)
            batch = []
    if batch:
        entries.objects.using(database).bulk_create(batch)


class Migration(migrations.Migration):
    dependencies = [("attendance", "0001_attendance_audit")]
    operations = [
        migrations.RunPython(snapshot_existing_records, migrations.RunPython.noop)
    ]
