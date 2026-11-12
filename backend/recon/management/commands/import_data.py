from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from recon.importer import import_all
from recon.models import Discrepancy
from recon.services import rebuild_discrepancies


class Command(BaseCommand):
    help = "Import system_a.csv, system_b.csv and locations.csv, then rebuild discrepancies."

    def add_arguments(self, parser):
        parser.add_argument("--data-dir", default=str(settings.DATA_DIR))
        parser.add_argument("--verbose-issues", action="store_true", help="Print every row-level parse issue")

    def handle(self, *args, data_dir, verbose_issues, **opts):
        # Import and rebuild commit together: a failed rebuild must not leave new rows
        # next to the previous import's discrepancies.
        try:
            with transaction.atomic():
                run = import_all(data_dir)
                counts = rebuild_discrepancies()
        except FileNotFoundError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"Import run #{run.pk}")
        for name, s in run.stats.items():
            dropped = s["rows_read"] - s["rows_stored"]
            self.stdout.write(
                f"  {name:10} read={s['rows_read']:4} stored={s['rows_stored']:4} "
                f"rows_with_issues={len(s['issues']):3} rejected={dropped}"
            )
            if verbose_issues:
                for issue in s["issues"]:
                    self.stdout.write(f"      line {issue['line']}: {'; '.join(issue['errors'])}")

        self.stdout.write("Discrepancies:")
        for (org, reason), n in sorted(counts.items()):
            self.stdout.write(f"  {org:16} {reason:18} {n}")
        for d in Discrepancy.objects.filter(org__isnull=True):
            self.stdout.write(self.style.WARNING(f"  operator-only: {d.reason} {d.record_id} {d.entry_ids} - {d.detail}"))
