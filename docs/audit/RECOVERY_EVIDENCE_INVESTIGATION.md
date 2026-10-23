# Recovery Evidence Investigation

**Status:** Read-only forensic investigation. No database was restored, no migration was run, and no deletion policy, model, view, migration, or test was changed.
**Repository:** `https://github.com/yohananX/bust-base.git` (**public**)
**Baseline commit:** `8a1bdcc287826253ee51bf9d2e3619706ee15546` (`main`)
**Investigated:** `2026-10-23`
**Companion document:** `docs/audit/HISTORICAL_DATA_LOSS_REVIEW.md` (code-proven loss capability). This document answers the next question: **what evidence survives, and in which environments did the destructive migrations actually run?**

---

## 0. Decision summary (answers first)

| Question | Finding |
|---|---|
| **What backups exist?** | Two SQL dumps survive in Git history. Both are from **2026-09-09**, both are **post-`0017`/`0018`**, and both contain **zero fee, invoice, payment, student, or academic rows**. They are schema/seed snapshots, not financial-history backups. |
| **Is the missing `backup_20260922_082845.sql.gz` present?** | **No.** It is absent from the working tree, every accessible filesystem path, Git objects, releases, artifacts, and trash. It cannot be recovered from this environment. |
| **Which environments applied the migrations?** | **Proven:** local SQLite (all 23 fees migrations through `0022`), a PostgreSQL 17.10 staging/seed database (through `0019`, including `0017`/`0018`), and GitHub Actions CI on PostgreSQL 16 (ephemeral). **Unverified:** Docker Compose PostgreSQL and any external/production PostgreSQL. |
| **Did any known populated database run `0017`/`0018`?** | **No evidence.** In both known migrated databases, `0017`/`0018` ran during a fresh `migrate` **before** any school, student, fee, or invoice row existed. |
| **Is a restore justified?** | **No — not for data recovery.** The surviving dumps contain no financial or academic data, and they post-date the destructive migrations. A restore would only reproduce an empty 2026-09-09 schema/seed. |
| **What data needs reconciliation?** | **None identifiable from current evidence**, because no populated database or pre-migration backup was found. If a populated production copy surfaces, use the reconciliation queries in `HISTORICAL_DATA_LOSS_REVIEW.md` §5.3. |
| **What containment should be authorized first?** | **(1) The public dump exposure** — the two dumps are publicly downloadable and contain password hashes; **(2) freeze unattended `migrate --noinput`**; **(3) acquire production/volume evidence**. Deletion-policy changes are **deferred** and were not made. |

**Overall verdict:** The available evidence does **not** show that historical financial or academic data was lost. It also does **not** prove that no loss occurred, because no populated production database or pre-migration backup was available. What it does prove is that **no recoverable pre-migration backup currently exists in evidence**, so a restore cannot undo `0017`/`0018` even if one were attempted.

---

## 1. Scope, method, and constraints

### 1.1 What was examined

- Git history, refs, unreachable objects, reflog, stash, tags, releases, and artifacts.
- The working tree, `db.sqlite3` (read-only), `media/`, and accessible filesystem locations.
- The two surviving SQL dumps, extracted to `/tmp/opencode/forensics` and parsed as text. **They were not loaded into any database.**
- Django migration records in the local SQLite database.
- Repository deployment/CI configuration and public GitHub metadata.
- Host process list and PostgreSQL/Docker availability.

### 1.2 Evidence labels

| Label | Meaning |
|---|---|
| **PROVEN** | Directly observed in source, Git objects, file metadata, parsed dump content, or read-only DB queries. |
| **UNVERIFIED** | Consistent with evidence but dependent on systems not accessible here. |
| **NOT RUN** | Deliberately not executed (restore, migration, destructive test, authenticated API call). |

### 1.3 Hard constraints observed

- No database restore, no `migrate`, no `pg_restore`, no `psql`, no data deletion.
- No application code, migration, model, test, deletion policy, or Git ref was modified.
- No production system was contacted and no credentials were requested or used.
- New artefacts were written only under `/tmp/opencode/forensics` (mode `0700`; dump copies mode `0600`).
- The only repository change is this document.

---

## 2. Backup inventory

### 2.1 Inventory table

| Candidate | Status | Contains financial/academic history? | Usable for recovery? |
|---|---|---|---|
| `backups/backup_20260909_154806.sql.gz` | **Exists in Git** (not working tree) | **No** — 0 students, 0 fees, 0 invoices | No (schema/seed only) |
| `backups/backup_20260909_161024.sql.gz` | **Exists in Git** (not working tree) | **No** — 0 students, 0 fees, 0 invoices | No (schema/seed only) |
| `backups/backup_20260922_082845.sql.gz` | **Missing** | Unknown; would be post-`0022` | Not found |
| `db.sqlite3` (local) | Exists | **No** — created empty on 2026-10-22 | No (not a backup) |
| Docker Compose `postgres_data` volume | Exists on host but **inaccessible** | Unknown | Unknown |
| GitHub releases / Actions artifacts | None (0 / 0) | — | — |
| Repository forks | None (0) | — | — |
| `media/fees/proofs/2026/10/*.png` | 3 files, 24 bytes each | No — placeholder bytes | No |
| `/root`, `/media/root`, `/media/yohananx` | Inaccessible (permissions) | Unknown | Unknown |
| External/provider backups | Not accessible | Unknown | Unknown |

### 2.2 The two recoverable dumps: provenance and access

Both files still exist as Git blobs:

| Dump | Blob SHA-1 | Size (bytes) | SHA-256 of extracted file |
|---|---|---|---|
| `backup_20260909_154806.sql.gz` | `883c38786841f2fddc46823604b697803230134d` | 212,765 | `e924c037e2fbc8e445898d5f10acc0e58bf173110883bcb3c02e223e06387223` |
| `backup_20260909_161024.sql.gz` | `e668b3be933d5b9ec082130299225ffc09da2b2e` | 214,793 | `b285e66cef33e370112ec7034a50bc3442daa3a7eae8839a62ef069340ed600e` |

**Proven reachability:**

- Both blobs are reachable from two remote branches only:
  - `origin/dependabot/pip/django-6.1.2` (tip `1116d01`, 2026-10-14)
  - `origin/dependabot/pip/psycopg2-binary-2.9.13` (tip `c0fbc9e`, 2026-10-14)
- The original commit is `9c6ccba` (“feat: comprehensive updates across multiple modules”, 2026-09-09 19:13:50 +01). It is **not** an ancestor of `main`.
- The rewritten equivalent on `main` is `f084d05` (same message/date), which adds only `core/management/commands/backup_database.py` and **not** the dumps.
- Merge commits `8e2e24c` and `f341bab` (2026-09-10) also contain the dumps but are not ancestors of `HEAD`.
- `git rev-list --objects origin/main` does **not** include either blob. The exposure is via the two old Dependabot branches and the commit SHAs, not via `main`’s tip.

**The files are not gzip.** Despite the `.gz` suffix, `gzip -t` fails and `file` reports `ASCII text, with CRLF line terminators`. They are plain `pg_dump` SQL from **PostgreSQL 17.10**, produced with `--no-owner`/`--no-acl` style output and containing `\restrict` / `\unrestrict` meta-commands. Restoration would therefore require a PostgreSQL client that understands those meta-commands (17.6+, or an equivalently patched minor release) and must be fed to `psql`, not `pg_restore`.

### 2.3 What the dumps actually contain

Both dumps have **103 `django_migrations` rows**, ending at `fees.0019_payment_verify_attempted`. They do **not** include `0020`, `0021`, or `0022`.

| Table | Dump A (`154806`) | Dump B (`161024`) |
|---|---:|---:|
| `core_school` | 0 | 1 |
| `core_academicsession` | 0 | 1 |
| `core_term` | 0 | 3 |
| `students_schoolclass` | 0 | 6 |
| `students_student` | **0** | **0** |
| `students_classenrollment` | 0 | 0 |
| `fees_feecategory` | **0** | **0** |
| `fees_feeprice` | **0** | **0** |
| `fees_feestructure` | **0** | **0** |
| `fees_invoice` | **0** | **0** |
| `fees_invoicelineitem` | **0** | **0** |
| `fees_payment` | **0** | **0** |
| `fees_paymentlineitem` | **0** | **0** |
| `fees_feereceipt` | **0** | **0** |
| `fees_feepriceoverride` | **0** | **0** |
| `fees_invoiceresetlog` | **0** | **0** |
| `academics_score` | **0** | **0** |
| `academics_termresult` | **0** | **0** |
| `accounts_user` | 1 | 2 |
| `django_admin_log` | 0 | 9 |

Only four business tables are non-empty in either dump: `core_school`, `core_academicsession`, `core_term`, and `students_schoolclass`. Every financial and academic table is empty.

**Timeline inside the dumps (PROVEN):**

- Migrations applied: `2026-09-09 14:44:25` → `14:44:50 +01` (103 migrations in ~25 seconds — a fresh `migrate`).
- `fees.0017` applied: `2026-09-09 14:44:38`.
- `fees.0018` applied: `2026-09-09 14:44:38`.
- First school created: `2026-09-09 16:56:27 +01` — **2 h 11 m after** `0017`/`0018`.
- Admin activity (school, JSS1–SSS3, staff, user): `16:56:27` → `16:59:54 +01`.
- Dump A has no school; Dump B has the school/classes/users. Filenames appear to be UTC while DB timestamps are WAT (+01), which is consistent with the ordering.

**Conclusion:** in this environment, `0017` and `0018` ran against **empty** fee tables, before the school existed. They could not have deleted fee or invoice history that was not there.

### 2.4 The missing `backup_20260922_082845.sql.gz`

**PROVEN absent from:**

- The working tree and `backups/` directory.
- `/home`, `/tmp`, `/mnt`, `/var`, `/srv`, `/opt`, `/media`.
- Git objects (`git rev-list --objects --all | grep 20260922` → no match).
- Releases (0) and Actions artifacts (0).
- Trash and cache locations.
- Shell history and local `~/.pgpass`, `~/.pg_service.conf`, `~/.aws/config` (none exist).

**Not inspectable without authorization:**

- `/root` (`0700`)
- `/media/root`, `/media/yohananx` (ACL/root-only)
- Docker volumes under `/var/lib/docker/volumes` (permission denied; user is not in the `docker` group; no rootless Docker)
- Any remote host, object store, or provider backup

The documented existence of this file is therefore a **lead**, not a recoverable artefact. Even if found, a 2026-09-22 dump would be **post-`0017`, post-`0018`, and post-`0022`** — it could document the post-loss state but could not recover data deleted on 2026-09-09.

### 2.5 Other candidate evidence

- **Local `db.sqlite3`:** created 2026-10-22 16:19; all 23 fees migrations applied by 16:19:48; school created 16:22:37. Contains 1 school, 2 users, 3 terms, and **0** fee categories, prices, invoices, payments, receipts, scores, or audit logs. It is a fresh development database, not a backup.
- **`media/fees/proofs/2026/10/`:** three 24-byte files containing the PNG signature plus the literal bytes `fake-image-bytes`. They are test placeholders, not real payment proofs.
- **Docker:** a PostgreSQL process is running on the host, but it is serving a **`noema`** database (unrelated project). There is no `bust-base`-specific service, database binary (`psql`, `pg_dump`, `postgres`), or data directory accessible. The Compose `postgres_data` volume cannot be inspected.
- **GitHub:** 0 releases, 0 artifacts, 0 forks, 0 deployments, 0 environments.

### 2.6 Backup inventory conclusion

**No pre-migration backup of a populated database exists in accessible evidence.** The only two dumps were taken **after** the destructive migrations, during a fresh setup, and contain no financial or academic rows. The one potentially relevant file (`backup_20260922_082845.sql.gz`) is missing and would be post-migration anyway.

---

## 3. Critical finding: the “purged” dumps are still public

### 3.1 Facts

- The repository is **public**: `"private": false`, `"visibility": "public"`.
- `docs/AUDIT_STATUS.md` states the dumps were “already purged from git history” and that `git log --all --full-history -- <paths>` “returns no commits — confirmed clean”.
- That verification is **false in the current clone**. Running the exact documented command returns:
  - `f341bab` — Merge branch `agents/mobile-friendly-admin-pages-review`
  - `8e2e24c` — Merge branch `agents/fix-onboarding-alert-links`
  - `9c6ccba` — the original dump commit
- The files are downloadable **without authentication**:
  - `https://raw.githubusercontent.com/yohananX/bust-base/dependabot/pip/django-6.1.2/backups/backup_20260909_154806.sql.gz` → **HTTP 206**, `content-range: bytes 0-0/212765`
  - The same path on the other Dependabot branch → **HTTP 206**
  - Commit-level access also works: `/9c6ccba/...` and `/f341bab/...` → **HTTP 206**
  - GitHub blob pages at those commit SHAs → **HTTP 200**
  - The same path on `main` → **HTTP 404** (deleted at tip, but still in history)
- Deleting the two branches alone would **not** remove commit-level access. GitHub Support cache/history purge is required for the commit SHAs.

### 3.2 What is exposed

- **Two `pbkdf2_sha256` password hashes** (89 characters each), one superuser and one ADMIN account.
- Usernames, names, and one Gmail address.
- A school seed row (“Grace House International School”), 3 terms, and 6 class rows.
- **Two `django_session` rows** in Dump B, with expiry `2026-09-23 16:54` and `2026-09-23 17:00 +01`. These are **expired** as of 2026-10-23, so they are not live sessions, but the rows still expose session identifiers.
- No student records, no payment data, no invoice data.

### 3.3 Why this matters

- This is a **live public credential exposure**, independent of the historical-loss question.
- It also explains why the earlier audit’s “purged” claim was believed: the files are gone from `main`’s tip, but the old history survives on two un-rewritten Dependabot branches.
- **No containment was performed.** Branch deletion, history rewrite, credential rotation, and GitHub Support contact all require explicit authorization and, for the dumps, a preserved controlled copy first.

---

## 4. Migration history by environment

### 4.1 Environment matrix

| ID | Environment | Database | Migrations proven applied | Applied when | Business data present | Evidence |
|---|---|---|---|---|---|---|
| **E1** | Local developer checkout | SQLite (`db.sqlite3`) | All 23 `fees` migrations through `0022` | `2026-10-22 16:19:16` → `16:19:48` | 0 fees/invoices/payments/students; 1 school, 2 users, 3 terms | Read-only `django_migrations` query |
| **E2** | Dump/staging environment | PostgreSQL **17.10** | `fees` through `0019` (includes `0017`, `0018`, `0020` **not** applied) | `2026-09-09 14:44:25` → `14:44:50 +01` | 0 fees/invoices/payments/students; school created `16:56:27` | Parsed dump `django_migrations` |
| **E3** | GitHub Actions CI | PostgreSQL **16** (service container) | All migrations via `python manage.py migrate` | Per CI run | Ephemeral test DB only | `.github/workflows/test.yml`; successful CI runs |
| **E4** | Docker Compose | PostgreSQL **16** (`postgres_data` volume) | Configured to auto-run in `entrypoint.sh` | Unknown | Unknown | `docker-compose.yml`, `entrypoint.sh`; volume inaccessible |
| **E5** | External/production | PostgreSQL (template only) | Unknown | Unknown | Unknown | `.env.production.example`; no real env committed; no GitHub deployment |

### 4.2 E1 — Local SQLite (PROVEN)

- `django_migrations` shows all migrations applied on **2026-10-22**, ending with `fees.0022_backfill_fee_price_and_line_item_names` at `16:19:44`.
- The school row was created at `16:22:37`, **after** migrations. Fee tables were empty throughout.
- The local database is therefore another fresh setup, not a restored production copy.

### 4.3 E2 — PostgreSQL 17.10 dump environment (PROVEN)

- 103 migrations applied in ~25 seconds on **2026-09-09 14:44:25–14:44:50 +01**.
- `fees.0017` and `fees.0018` both applied at `14:44:38`.
- The first school row appears at `16:56:27 +01`, over two hours later.
- All fee, invoice, payment, receipt, student, score, and result tables are empty at dump time.
- This is the **only known non-SQLite environment** where `0017`/`0018` demonstrably ran, and they ran on an empty database.

### 4.4 E3 — GitHub Actions CI (PROVEN, ephemeral)

- `.github/workflows/test.yml` starts `postgres:16`, writes a `DATABASE_URL`, runs `python manage.py migrate`, then `python manage.py test`.
- Successful CI runs on `main` (e.g. `9b2eff67`, `2026-09-23 09:40:53Z`; also `b3b76c89`, `82d6bef6`, `b0d6a759`, `81ab21ec`) prove the migration chain applies on PostgreSQL 16.
- CI uses a throwaway service container. It cannot contain production history. Successful runs demonstrate **compatibility**, not data safety.
- CI logs could not be downloaded without authentication (`HTTP 403`); no credentials were requested. The workflow definition and successful conclusions are sufficient to establish that `migrate` ran.

### 4.5 E4 — Docker Compose (UNVERIFIED)

- `docker-compose.yml` defines `postgres:16-alpine` with a persistent `postgres_data` volume.
- `entrypoint.sh` runs `python manage.py migrate --noinput` on every container start.
- Docker socket access is denied (`permission denied ... /var/run/docker.sock`), the user is not in the `docker` group, and no rootless Docker is present.
- **Unknown:** whether this stack has ever run, which migrations it applied, and whether its volume holds data or backups.
- This is the single largest accessible-evidence gap that could hide the missing 2026-09-22 backup or a populated database.

### 4.6 E5 — External/production (UNVERIFIED)

- The only production database configuration is `.env.production.example`, a template. No real `.env.production` was ever committed (`git log --all -- .env.production` → none).
- The Deploy workflow (`deploy.yml`) **only builds and pushes an image** to `ghcr.io`. It has no deploy, SSH, cloud, or migration step.
- GitHub reports **0 deployments** and **0 environments** for the repository.
- No Fly/Render/Railway/Heroku/Terraform/Kubernetes manifests exist.
- Therefore there is **no evidence in the repository or GitHub metadata that any image was actually run against a production database**. This does not prove one does not exist; it means the evidence is not available here.

### 4.7 Deploy image timeline (PROVEN builds, not deployments)

The Deploy workflow has **24 runs**: **14 successes** and **10 failures**. The successes cover **12 unique commits**. Mapping each successful commit to migration files present:

| First successful build | Commit | Contains `0017` | `0018` | `0020` | `0022` |
|---|---|:---:|:---:|:---:|:---:|
| 2026-09-11 06:53Z | `6ca9604b` | Y | Y | Y | – |
| 2026-09-15 20:07Z | `1c2c271c` | Y | Y | Y | – |
| 2026-09-16 06:02Z | `91285857` | Y | Y | Y | – |
| 2026-09-16 06:44Z | `81ab21ec` | Y | Y | Y | – |
| 2026-09-16 07:56Z | `b0d6a759` | Y | Y | Y | – |
| 2026-09-16 15:06Z | `82d6bef6` | Y | Y | Y | Y |
| 2026-09-23 07:55Z | `9567d0d2` | Y | Y | Y | Y |
| 2026-09-23 08:02Z | `20026c16` | Y | Y | Y | Y |
| 2026-09-23 09:37Z | `b3b76c89` | Y | Y | Y | Y |
| 2026-09-23 09:40Z | `9b2eff67` | Y | Y | Y | Y |
| 2026-09-23 09:53Z | `dabdbef6` | Y | Y | Y | Y |
| 2026-09-24 04:33Z | `d508220b` | Y | Y | Y | Y |
| 2026-10-10 17:21Z | `d508220b` | Y | Y | Y | Y |

Key points:

- **Destructive-migration images were built from 2026-09-11 onward.** Whether any was pulled and started is not recorded.
- **Deploy succeeded while CI failed** on `d508220b` (2026-09-24 and 2026-10-10). The Deploy workflow does not depend on CI, so images can be pushed even when tests are red.
- The first successful image with `0017`/`0018` (`6ca9604b`, 2026-09-11) post-dates the staging dump (`2026-09-09`). The staging database was migrated directly from source, not from that image.

### 4.8 Migration commit timeline (for reference)

| Migration | Landed on `main` | Note |
|---|---|---|
| `0017_cleanup_duplicate_one_time_prices` | 2026-09-02 14:42 +01 | `81fd0e5` |
| `0018_delete_school_fees_categories` | 2026-09-05 10:27 +01 | `26de126` |
| `0020_remove_feecategory_group_and_more` | 2026-09-09 22:26 +01 | `1f273a0` / `df697f3` |
| `0022_backfill_fee_price_and_line_item_names` | 2026-09-16 15:42 +01 | `5f7315c` / `5387a2d` |

---

## 5. What the evidence means for recovery

### 5.1 There is no pre-destructive backup

To recover data deleted by `0017`/`0018`, a backup must have been taken **before** those migrations ran in the affected environment. The evidence shows:

- The two surviving dumps were taken **after** `0017`/`0018` (migrations at 14:44; dumps later that afternoon) and contain **zero** affected rows.
- The missing `backup_20260922_082845.sql.gz` would be **after** `0017`, `0018`, `0020`, and `0022`.
- The local SQLite database was created **after** all migrations, on 2026-10-22.
- No other backup, snapshot, release asset, artifact, or fork was found.

**Therefore: no accessible artefact can restore data deleted by `0017`/`0018`.** A restore of the surviving dumps would reproduce an empty 2026-09-09 schema and seed, not historical fees or invoices.

### 5.2 Restore assessment

| Restore option | Justified? | Reason |
|---|---|---|
| Restore Dump A or B into a live database | **No** | Empty financial data; post-migration; would overwrite current schema/seed for no recovery benefit. |
| Restore either dump into an isolated scratch DB for forensic schema analysis | **Optional** | Could reproduce the exact `0019` schema and seed to study `0020`–`0022`. Not needed for loss recovery. |
| Restore `backup_20260922_082845.sql.gz` if found | **Only for reconciliation** | Post-migration; can measure post-loss state, not recover pre-loss data. |
| Restore a newly discovered pre-2026-09-09 populated backup | **Yes, into isolation** | The only path that could recover deleted history, and only if one exists. |
| Restore a current production dump | **Yes, read-only** | Needed to measure surviving data and reconcile invoices/payments. |

### 5.3 Reconciliation scope

From current evidence: **nothing to reconcile**, because no populated database or backup was found. If a populated copy surfaces (E4/E5, a provider backup, or a newly found pre-migration dump), the following must be measured before any repair:

1. Invoice `total_amount` vs `SUM(line_items.amount)` per invoice.
2. Invoices with zero surviving line items but non-zero totals.
3. `PaymentLineItem` rows with `category_id IS NULL` or `invoice_id` pointing at an invoice with missing lines.
4. Surviving `FeeCategory` / `FeePrice` history vs provider/Paystack records.
5. `FeeReceipt` presence vs `Payment` records.
6. `InvoiceResetLog` and `AuditLog` entries for operator-initiated deletions.
7. Paystack transaction exports (amounts, references, dates) to cross-check payments and receipts.

The concrete SQL is in `docs/audit/HISTORICAL_DATA_LOSS_REVIEW.md` §5.3. It must be run against a **restored, read-only** copy, never production.

### 5.4 What would change the conclusion

The conclusion “no proven loss” would change to “loss confirmed” only if one of these appears:

- A populated database that ran `0017`/`0018` with fee/invoice rows present.
- A pre-2026-09-09 backup of a populated database.
- Provider records showing payments/receipts with no corresponding surviving rows.
- An invoice whose total exceeds its surviving line items by amounts consistent with deleted `School Fees` categories.
- A confirmed deployment log showing a destructive image started against a populated database.

None of these were found.

---

## 6. Proven vs unverified

### 6.1 Proven

1. Two SQL dumps exist in Git, are reachable from two Dependabot branches, and are publicly downloadable at branch and commit level.
2. Both dumps are plain SQL (not gzip), from PostgreSQL 17.10, and stop at `fees.0019`.
3. Both dumps were taken after `0017`/`0018`, which ran during a fresh `migrate` on 2026-09-09 at 14:44:38.
4. The first school in the dump environment was created at 16:56:27, over two hours after those migrations.
5. Both dumps contain zero fee, invoice, payment, receipt, student, score, and result rows.
6. The local SQLite database applied all migrations through `0022` on 2026-10-22 and has zero fee/invoice/payment/student rows.
7. `backup_20260922_082845.sql.gz` is absent from every accessible location.
8. The repository is public; the two dumps expose two password hashes and expired session identifiers.
9. `docs/AUDIT_STATUS.md`’s “no traces remain” claim is contradicted by the exact verification command it documents.
10. CI runs migrations on ephemeral PostgreSQL 16 and has succeeded on `main`.
11. The Deploy workflow only builds/pushes images; it records no deployment step.
12. Fourteen Deploy runs succeeded, covering twelve unique commits; images from 2026-09-11 onward contain `0017`/`0018`.
13. Deploy succeeded while CI failed for `d508220b` (2026-09-24 and 2026-10-10).
14. No releases, artifacts, forks, or GitHub deployments/environments exist.

### 6.2 Unverified

1. Whether any image was actually run against a production database.
2. Whether a production/external database exists at all.
3. Whether the Docker Compose `postgres_data` volume contains data or backups.
4. Whether `/root` or `/media/*` contains the missing 2026-09-22 dump.
5. Whether the PostgreSQL 17.10 dump environment later became production and received students/fees.
6. Whether any earlier, pre-2026-09-09 populated backup exists outside this host.
7. Whether `0017`/`0018` ever ran against populated data in any environment.
8. Whether any operator used the live hard-delete paths after migrations.
9. Whether PostgreSQL enforced any additional constraints beyond Django’s configured cascade.
10. The exact CI migration log (API returned 403 without authentication).

### 6.3 What cannot be claimed

- That data **was** lost in production.
- That data was **not** lost in production.
- That a restore can recover deleted fees or invoices.
- That the surviving dumps are a usable financial backup.
- That the public exposure has been contained.

---

## 7. Containment and evidence-preservation actions to authorize

Nothing below has been implemented. They are ordered by urgency and separated so the user can authorize the public-leak response without authorizing deletion-policy changes or a restore.

### 7.1 Authorize first — public dump exposure (urgent, independent of data loss)

1. **Preserve controlled copies before any purge.**
   The two dumps are already copied to `/tmp/opencode/forensics` with mode `0600` and recorded SHA-256 checksums. Move them to an access-controlled evidence store, record chain of custody, and restrict access. Do not commit them.
2. **Rotate the exposed credentials.**
   Reset the passwords for the superuser and ADMIN accounts in the dump (and any environment where those accounts are still active). Invalidate sessions; the two dumped sessions are expired, but rotate the accounts anyway.
3. **Remove public access.**
   Delete or rewrite the two Dependabot branches, then contact GitHub Support to purge the commit-level cache for `9c6ccba`, `f341bab`, `8e2e24c`, `883c3878…`, and `e668b3be…`. Branch deletion alone leaves commit URLs working.
4. **Verify.**
   After purge, re-check the raw URLs and blob pages for `main`, both branch names, and the commit SHAs; expect 404s. Re-run `git log --all --full-history -- <paths>` and `git rev-list --objects --all | grep <blob>` to confirm no ref reaches them.
5. **Check for forks/leaks.**
   No forks exist today. Re-check after any public window; consider GitHub secret scanning alerts.

**Note:** this is repository hygiene and credential response. It is not a deletion-policy change and does not touch application data.

### 7.2 Authorize second — stop unattended destructive migrations

6. **Freeze `migrate --noinput` on container start.**
   Remove it from `entrypoint.sh`, or gate it behind an explicit release flag. A destructive `RunPython` must never run automatically on a populated database.
7. **Make Deploy depend on CI.**
   The Deploy workflow currently pushes images even when CI fails. Require a green CI run (or a manual approval environment) before pushing `latest`.

### 7.3 Authorize third — close the evidence gaps

8. **Inspect the Docker Compose volume.**
   Requires Docker group access or an authorized `sudo` read-only inspection. Look for `postgres_data` and any `backups/` directory.
9. **Inspect `/root` and `/media/*`.**
   Requires authorized access. Look specifically for `backup_20260922_082845.sql.gz`.
10. **Obtain production evidence, read-only.**
    - `django_migrations` rows for `fees.0017`, `0018`, `0020`, `0022` per environment.
    - A current dump or read-only replica, if a production DB exists.
    - Container start logs / deploy logs from the hosting provider.
    - Paystack transaction exports.
11. **Run the reconciliation queries** from `HISTORICAL_DATA_LOSS_REVIEW.md` §5.3 against an isolated restore, if and only if a populated copy is obtained.

### 7.4 Deferred — deletion-policy changes

Per instruction, **do not change deletion policies yet.** The recommendations in `HISTORICAL_DATA_LOSS_REVIEW.md` §6 (guard fee-category deletion on `InvoiceLineItem`, `PROTECT`/`SET_NULL` for `InvoiceLineItem.category`, `Payment.recorded_by`, `Score.entered_by`, archive/reversal instead of hard delete, audit coverage) remain pending until the evidence in 7.3 is gathered and the restore decision is made.

### 7.5 Not done in this investigation

- No branch deletion, history rewrite, force-push, or GitHub Support contact.
- No credential rotation or session invalidation.
- No database restore, migration, `psql`, or `pg_restore`.
- No change to models, views, migrations, tests, or deletion policies.
- No authenticated GitHub API call and no production contact.

---

## 8. Decisions required

| # | Decision | Recommended option | Why it is needed |
|---|---|---|---|
| 1 | Treat the public dump exposure as an incident? | **Yes** | Password hashes are publicly downloadable and commit-level access survives branch deletion. |
| 2 | Authorize preservation of controlled dump copies? | **Yes** | Needed for chain of custody before purging public copies. |
| 3 | Authorize branch deletion + GitHub Support purge? | **Yes** | Removes the only confirmed public path to the dumps. |
| 4 | Rotate the two dumped accounts and invalidate sessions? | **Yes** | Mitigates credential exposure; sessions are expired but accounts may persist. |
| 5 | Freeze `migrate --noinput`? | **Yes** | Prevents another destructive migration from running unattended. |
| 6 | Authorize Docker/volume and `/root`/`/media` inspection? | **Yes, read-only** | The missing 2026-09-22 dump and any populated DB may be there. |
| 7 | Is a restore justified now? | **No** | No pre-migration populated backup exists; dumps are empty and post-migration. |
| 8 | Acquire production evidence or confirm none exists? | **Yes** | The only way to move from “no evidence” to a quantified answer. |
| 9 | Authorize deletion-policy changes now? | **No — defer** | Per instruction; wait for evidence and the restore decision. |
| 10 | Notify affected users/schools? | **Pending evidence** | Depends on whether production credentials/data were exposed beyond the public dumps. |

---

## 9. Integrity statement

This investigation was read-only. No application code, migration, model, test, deletion policy, database, or Git object was modified, staged, committed, reverted, or cleaned. No database was restored. No migration was run. No production system was contacted and no credentials were requested or used.

The two dumps were copied out of Git into `/tmp/opencode/forensics` and parsed as text; they were **not** loaded into any database. The copies are mode `0600`, the directory is mode `0700`, and SHA-256 checksums are recorded in `/tmp/opencode/forensics/SHA256SUMS.txt`.

The only repository change is the addition of this document at `docs/audit/RECOVERY_EVIDENCE_INVESTIGATION.md`.

---

## Appendix A — Key evidence references

### A.1 Git objects and refs

```
Dump A blob: 883c38786841f2fddc46823604b697803230134d  (212,765 bytes)
Dump B blob: e668b3be933d5b9ec082130299225ffc09da2b2e  (214,793 bytes)
Original commit: 9c6ccba  (not an ancestor of HEAD)
Rewritten commit: f084d05 (ancestor of HEAD; dumps removed)
Merge commits containing dumps: 8e2e24c, f341bab (not ancestors of HEAD)
Reachable only via:
  refs/remotes/origin/dependabot/pip/django-6.1.2            (1116d01)
  refs/remotes/origin/dependabot/pip/psycopg2-binary-2.9.13  (c0fbc9e)
```

### A.2 Public access checks

```
raw.githubusercontent.com/.../dependabot/pip/django-6.1.2/backups/backup_20260909_154806.sql.gz -> 206
raw.githubusercontent.com/.../dependabot/pip/psycopg2-binary-2.9.13/...                          -> 206
raw.githubusercontent.com/.../9c6ccba/backups/backup_20260909_154806.sql.gz                      -> 206
raw.githubusercontent.com/.../f341bab/backups/backup_20260909_161024.sql.gz                      -> 206
github.com/.../blob/9c6ccba/backups/backup_20260909_154806.sql.gz                                -> 200
github.com/.../blob/f341bab/backups/backup_20260909_161024.sql.gz                                -> 200
raw.githubusercontent.com/.../main/backups/backup_20260909_154806.sql.gz                         -> 404
Content-Range: bytes 0-0/212765
```

### A.3 Dump migration rows (excerpt)

```
fees 0017_cleanup_duplicate_one_time_prices        2026-09-09 14:44:38
fees 0018_delete_school_fees_categories            2026-09-09 14:44:38
fees 0019_payment_verify_attempted                 2026-09-09 14:44:39
students 0007_student_student_type                 2026-09-09 14:44:50
```

### A.4 Table counts (both dumps)

```
                     Dump A   Dump B
core_school              0        1
core_academicsession     0        1
core_term                0        3
students_schoolclass     0        6
students_student         0        0
fees_feecategory         0        0
fees_feeprice            0        0
fees_invoice             0        0
fees_invoicelineitem     0        0
fees_payment             0        0
fees_feereceipt          0        0
academics_score          0        0
academics_termresult     0        0
accounts_user            1        2
django_admin_log         0        9
django_migrations      103      103
```

### A.5 Local migration record (excerpt)

```
fees.0017  2026-10-22 16:19:42.639199
fees.0018  2026-10-22 16:19:42.912015
fees.0020  2026-10-22 16:19:43.586646
fees.0021  2026-10-22 16:19:44.080593
fees.0022  2026-10-22 16:19:44.251954
core_school.created_at  2026-10-22 16:22:37
```

### A.6 GitHub metadata

```
Repo: yohananX/bust-base
private: false
visibility: public
forks: 0
releases: 0
artifacts: 0
deployments: 0
environments: 0
Deploy runs: 24 total / 14 success / 10 failure
CI latest successful main run: 9b2eff67 (2026-09-23T09:40:53Z)
CI logs without auth: HTTP 403 (not requested)
```
