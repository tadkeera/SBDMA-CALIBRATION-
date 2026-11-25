'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  KeyRound,
  Lock,
  LockOpen,
  Search,
  ShieldAlert,
  ShieldCheck,
  UserCog,
  UserPlus,
  UserX,
} from 'lucide-react';
import { useApp } from '@/components/AppProvider';
import { Card, EmptyState, Field, Metric, Modal, Skeleton, Toolbar } from '@/components/ui';
import { ApiError, api, type ServerManagedUser, type ServerRoleOption } from '@/core/api/client';

/**
 * Account administration.
 *
 * The server is the authority on what may be granted: it refuses roles above
 * your rank and refuses approval roles to anyone who administers accounts, so
 * this page only *reflects* those rules. The UI still marks the forbidden
 * options clearly instead of hiding them — an operator who cannot see why an
 * action is unavailable will keep retrying it, and "why" is an audit question.
 */
export default function UsersPage() {
  const { t, lang, notify, can, user: me } = useApp();
  const allowed = can('users.manage');

  const [rows, setRows] = useState<ServerManagedUser[]>([]);
  const [roles, setRoles] = useState<ServerRoleOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');
  const [onlyInactive, setOnlyInactive] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [target, setTarget] = useState<ServerManagedUser | null>(null);

  const load = useCallback(async () => {
    if (!allowed) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const [users, roleOptions] = await Promise.all([
        api.users({ q: q || undefined, active: onlyInactive ? false : undefined }),
        api.roleOptions(),
      ]);
      setRows(users);
      setRoles(roleOptions);
    } catch (error) {
      notify(
        'error',
        t('تعذّر تحميل المستخدمين', 'Could not load users'),
        error instanceof ApiError ? error.text(lang) : String(error),
      );
    } finally {
      setLoading(false);
    }
  }, [allowed, lang, notify, onlyInactive, q, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const stats = useMemo(
    () => ({
      total: rows.length,
      active: rows.filter((r) => r.is_active).length,
      locked: rows.filter((r) => r.is_locked).length,
      pending: rows.filter((r) => r.must_change_password).length,
    }),
    [rows],
  );

  const act = async (label: string, fn: () => Promise<unknown>, success: string) => {
    setBusy(label);
    try {
      await fn();
      notify('success', success);
      await load();
    } catch (error) {
      notify(
        'error',
        t('رُفض الإجراء', 'Action refused'),
        error instanceof ApiError ? error.text(lang) : String(error),
      );
    } finally {
      setBusy(null);
    }
  };

  if (!allowed) {
    return (
      <Card>
        <EmptyState
          title={t('غير مصرح', 'Not permitted')}
          detail={t(
            'إدارة الحسابات تتطلب صلاحية users.manage، وهي محصورة بمسؤولي النظام.',
            'Account administration requires users.manage, which only system administrators hold.',
          )}
        />
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      <Toolbar>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 rounded-lg border px-2 py-1">
            <Search size={16} />
            <input
              className="w-full bg-transparent text-[12px] outline-none"
              value={q}
              onChange={(event) => setQ(event.target.value)}
              placeholder={t('بحث بالاسم أو البريد', 'Search name or e-mail')}
              aria-label={t('بحث', 'Search')}
            />
          </label>
          <label className="flex items-center gap-1.5 text-[12px]">
            <input
              type="checkbox"
              checked={onlyInactive}
              onChange={(event) => setOnlyInactive(event.target.checked)}
            />
            <span>{t('المعطّلون فقط', 'Disabled only')}</span>
          </label>
        </div>
        <button className="btn btn-primary" onClick={() => setCreateOpen(true)}>
          <UserPlus size={16} />
          {t('حساب جديد', 'New account')}
        </button>
      </Toolbar>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label={t('إجمالي الحسابات', 'Accounts')} value={stats.total} />
        <Metric label={t('نشط', 'Active')} value={stats.active} tone="pass" />
        <Metric label={t('مقفل', 'Locked')} value={stats.locked} tone={stats.locked ? 'fail' : 'neutral'} />
        <Metric
          label={t('بانتظار تغيير كلمة المرور', 'Must change password')}
          value={stats.pending}
          tone={stats.pending ? 'warn' : 'neutral'}
        />
      </div>

      <Card
        title={t('سجل المستخدمين', 'User register')}
        subtitle={t(
          'الحسابات لا تُحذف مطلقاً — تُعطّل فقط، لتبقى التوقيعات التاريخية مرتبطة بأشخاص حقيقيين',
          'Accounts are never deleted, only disabled, so historical signatures keep pointing at real people',
        )}
      >
        {loading ? (
          <Skeleton rows={6} />
        ) : rows.length === 0 ? (
          <EmptyState title={t('لا يوجد مستخدمون مطابقون', 'No matching users')} />
        ) : (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>{t('المستخدم', 'User')}</th>
                  <th>{t('الأدوار', 'Roles')}</th>
                  <th>{t('الحالة', 'Status')}</th>
                  <th>{t('آخر دخول', 'Last sign-in')}</th>
                  <th>{t('إجراءات', 'Actions')}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const isMe = row.id === me?.id;
                  return (
                    <tr key={row.id}>
                      <td>
                        {/* flex, not space-y: strong/span are inline, so vertical
                            spacing utilities had no effect and the three values
                            collapsed onto one line */}
                        <div className="flex flex-col gap-0.5">
                          <strong>{lang === 'ar' ? row.full_name_ar : row.full_name_en}</strong>
                          <span className="font-mono text-[11px] text-[var(--text-muted)]">{row.username}</span>
                          <span className="text-[11px] text-[var(--text-muted)]">{row.email}</span>
                        </div>
                      </td>
                      <td>
                        <div className="flex flex-wrap gap-1.5">
                          {row.roles.map((code) => (
                            <span key={code} className="chip font-mono text-[10.5px]">
                              {code}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td>
                        <div className="flex flex-wrap gap-1.5">
                          {row.is_active ? (
                            <span className="chip">
                              <ShieldCheck size={13} /> {t('نشط', 'Active')}
                            </span>
                          ) : (
                            <span className="chip">
                              <UserX size={13} /> {t('معطّل', 'Disabled')}
                            </span>
                          )}
                          {row.is_locked && (
                            <span className="chip">
                              <Lock size={13} /> {t('مقفل', 'Locked')}
                            </span>
                          )}
                          {row.must_change_password && (
                            <span className="chip">
                              <KeyRound size={13} /> {t('يجب تغيير الكلمة', 'Change required')}
                            </span>
                          )}
                          {isMe && <span className="chip">{t('أنت', 'You')}</span>}
                        </div>
                      </td>
                      <td className="font-mono text-[11px]">
                        {row.last_login_at
                          ? new Date(row.last_login_at).toLocaleString(lang === 'ar' ? 'ar-YE' : 'en-GB')
                          : '—'}
                      </td>
                      <td>
                        <button className="btn btn-ghost" onClick={() => setTarget(row)} disabled={isMe}>
                          <UserCog size={15} />
                          {t('إدارة', 'Manage')}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {createOpen && (
        <CreateUserDialog
          roles={roles}
          busy={busy !== null}
          onClose={() => setCreateOpen(false)}
          onSubmit={async (payload) => {
            await act(
              'create',
              () => api.createUser(payload),
              t('أُنشئ الحساب — عليه تغيير كلمة المرور عند أول دخول', 'Account created — must change password at first sign-in'),
            );
            setCreateOpen(false);
          }}
        />
      )}

      {target && (
        <ManageUserDialog
          user={target}
          roles={roles}
          busy={busy !== null}
          onClose={() => setTarget(null)}
          onDone={() => {
            setTarget(null);
            void load();
          }}
        />
      )}
    </div>
  );
}

// ───────────────────────────── create ────────────────────────────────────── //

function CreateUserDialog({
  roles,
  busy,
  onClose,
  onSubmit,
}: {
  roles: ServerRoleOption[];
  busy: boolean;
  onClose: () => void;
  onSubmit: (payload: {
    username: string;
    email: string;
    full_name_ar: string;
    full_name_en: string;
    password: string;
    roles: string[];
    reason: string;
  }) => Promise<void>;
}) {
  const { t, lang } = useApp();
  const [form, setForm] = useState({
    username: '',
    email: '',
    full_name_ar: '',
    full_name_en: '',
    password: '',
    reason: '',
  });
  const [selected, setSelected] = useState<string[]>(['ANALYST']);

  const toggle = (code: string) =>
    setSelected((prev) => (prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]));

  return (
    <Modal open title={t('إنشاء حساب مستخدم', 'Create account')} onClose={onClose}>
      <div className="space-y-3">
        <p className="text-[11px] text-[var(--text-muted)]">
          {t(
            'كل إنشاء حساب يُسجَّل في سلسلة التدقيق بسبب مكتوب. الحساب يبدأ بطلب تغيير كلمة المرور.',
            'Every account creation is written to the audit chain with a documented reason. The account starts with a forced password change.',
          )}
        </p>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t('اسم المستخدم', 'Username')}>
            <input className="input"
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
              dir="ltr"
              autoComplete="off"
            />
          </Field>
          <Field label={t('البريد الإلكتروني', 'E-mail')}>
            <input className="input"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              dir="ltr"
              autoComplete="off"
            />
          </Field>
          <Field label={t('الاسم الكامل (عربي)', 'Full name (Arabic)')}>
            <input className="input" value={form.full_name_ar} onChange={(e) => setForm({ ...form, full_name_ar: e.target.value })} />
          </Field>
          <Field label={t('الاسم الكامل (إنجليزي)', 'Full name (English)')}>
            <input className="input"
              value={form.full_name_en}
              onChange={(e) => setForm({ ...form, full_name_en: e.target.value })}
              dir="ltr"
            />
          </Field>
        </div>

        <Field
          label={t('كلمة المرور المؤقتة', 'Temporary password')}
          hint={t(
            '12 حرفاً على الأقل، مع حرف كبير وصغير ورقم ورمز',
            'At least 12 characters with upper, lower, digit and symbol',
          )}
        >
          <input className="input"
            type="password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            dir="ltr"
            autoComplete="new-password"
          />
        </Field>

        <Field
          label={t('الأدوار', 'Roles')}
          hint={t(
            'الأدوار المعطاة لا يمكن منحها إلا إذا كنت تحمل صلاحياتها. أدوار الاعتماد محجوبة عن مسؤول الحسابات لحماية فصل المهام.',
            'You can only grant roles whose permissions you hold. Approval roles are blocked for account administrators to protect separation of duties.',
          )}
        >
          <div className="flex flex-wrap gap-1.5">
            {roles.map((role) => (
              <button
                type="button"
                key={role.code}
                className={`chip ${selected.includes(role.code) ? 'chip-pass' : 'chip-quiet'}`}
                onClick={() => role.assignable && toggle(role.code)}
                disabled={!role.assignable}
                title={
                  role.assignable
                    ? `${role.name_ar} — ${role.permissions.join(', ')}`
                    : t('غير قابل للإسناد من حسابك', 'Not assignable from your account')
                }
              >
                {!role.assignable && <ShieldAlert size={13} />}
                {lang === 'ar' ? role.name_ar : role.name_en}
              </button>
            ))}
          </div>
        </Field>

        <Field label={t('سبب الإنشاء (يُسجَّل في التدقيق)', 'Reason (written to the audit trail)')}>
          <textarea className="textarea"
            rows={2}
            value={form.reason}
            onChange={(e) => setForm({ ...form, reason: e.target.value })}
            placeholder={t('مثال: تعيين محلل جديد في قسم الفيزياء', 'e.g. onboarding a new analyst in the physics lab')}
          />
        </Field>

        <div className="flex justify-end gap-2">
          <button className="btn btn-ghost" onClick={onClose}>
            {t('إلغاء', 'Cancel')}
          </button>
          <button
            className="btn btn-primary"
            disabled={busy || selected.length === 0 || form.reason.trim().length < 8}
            onClick={() =>
              onSubmit({
                username: form.username.trim(),
                email: form.email.trim(),
                full_name_ar: form.full_name_ar.trim(),
                full_name_en: form.full_name_en.trim(),
                password: form.password,
                roles: selected,
                reason: form.reason.trim(),
              })
            }
          >
            {t('إنشاء', 'Create')}
          </button>
        </div>
      </div>
    </Modal>
  );
}

// ───────────────────────────── manage ────────────────────────────────────── //

function ManageUserDialog({
  user,
  roles,
  busy,
  onClose,
  onDone,
}: {
  user: ServerManagedUser;
  roles: ServerRoleOption[];
  busy: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const { t, lang, notify } = useApp();
  const [reason, setReason] = useState('');
  const [selected, setSelected] = useState<string[]>(user.roles);
  const [password, setPassword] = useState('');

  const reasonOk = reason.trim().length >= 8;
  const run = async (label: string, fn: () => Promise<unknown>, ok: string) => {
    if (!reasonOk) {
      notify('warn', t('السبب مطلوب', 'A reason is required'), t('لا يقل عن 8 أحرف', 'At least 8 characters'));
      return;
    }
    try {
      await fn();
      notify('success', ok);
      onDone();
    } catch (error) {
      notify(
        'error',
        t('رُفض الإجراء', 'Action refused'),
        error instanceof ApiError ? error.text(lang) : String(error),
      );
    }
  };

  const rolesChanged = selected.length > 0 && [...selected].sort().join() !== [...user.roles].sort().join();

  return (
    <Modal open title={`${t('إدارة', 'Manage')} — ${user.username}`} onClose={onClose}>
      <div className="space-y-3">
        <Field label={t('سبب الإجراء (إلزامي)', 'Reason for the change (required)')}>
          <textarea className="textarea"
            rows={2}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={t('يُسجَّل حرفياً في سلسلة التدقيق', 'Recorded verbatim in the audit chain')}
          />
        </Field>

        <Field
          label={t('الأدوار', 'Roles')}
          hint={t('لا يمكنك تعديل أدوارك أنت، ولا منح دور أعلى من رتبتك.', 'You cannot edit your own roles, nor grant a role above your rank.')}
        >
          <div className="flex flex-wrap gap-1.5">
            {roles.map((role) => (
              <button
                type="button"
                key={role.code}
                className={`chip ${selected.includes(role.code) ? 'chip-pass' : 'chip-quiet'}`}
                disabled={!role.assignable}
                onClick={() =>
                  setSelected((prev) =>
                    prev.includes(role.code) ? prev.filter((c) => c !== role.code) : [...prev, role.code],
                  )
                }
              >
                {!role.assignable && <ShieldAlert size={13} />}
                {lang === 'ar' ? role.name_ar : role.name_en}
              </button>
            ))}
          </div>
        </Field>

        <div className="flex flex-wrap items-center gap-2">
          <button
            className="btn btn-ghost"
            disabled={busy || !rolesChanged}
            onClick={() =>
              run(
                'roles',
                () => api.updateUser(user.id, { roles: selected, reason: reason.trim() }),
                t('حُدّثت الأدوار', 'Roles updated'),
              )
            }
          >
            <UserCog size={15} /> {t('حفظ الأدوار', 'Save roles')}
          </button>

          <button
            className="btn btn-ghost"
            disabled={busy}
            onClick={() =>
              run(
                'active',
                () => api.updateUser(user.id, { is_active: !user.is_active, reason: reason.trim() }),
                user.is_active ? t('عُطّل الحساب', 'Account disabled') : t('أُعيد تفعيل الحساب', 'Account re-enabled'),
              )
            }
          >
            {user.is_active ? <UserX size={15} /> : <ShieldCheck size={15} />}
            {user.is_active ? t('تعطيل الحساب', 'Disable account') : t('إعادة التفعيل', 'Re-enable')}
          </button>

          {user.is_locked && (
            <button
              className="btn btn-ghost"
              disabled={busy}
              onClick={() =>
                run('unlock', () => api.unlockUser(user.id, reason.trim()), t('رُفع القفل', 'Lockout cleared'))
              }
            >
              <LockOpen size={15} /> {t('رفع القفل', 'Unlock')}
            </button>
          )}

          <button
            className="btn btn-ghost"
            disabled={busy}
            onClick={() =>
              run(
                'revoke',
                () => api.revokeUserSessions(user.id, reason.trim()),
                t('أُبطلت الجلسات', 'Sessions revoked'),
              )
            }
          >
            <Lock size={15} /> {t('إبطال الجلسات', 'Revoke sessions')}
          </button>
        </div>

        <Field
          label={t('إعادة تعيين كلمة المرور', 'Reset password')}
          hint={t(
            'تُبطل كل جلسات المستخدم فوراً ويُطلب منه التغيير عند الدخول. لا يمكنك إعادة تعيين كلمة مرور نفسك أو زميل معتمد.',
            'All of the user’s sessions are revoked immediately and a change is required at sign-in. You cannot reset your own password or a peer approver’s.',
          )}
        >
          <div className="flex flex-wrap items-center gap-2">
            <input className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              dir="ltr"
              autoComplete="new-password"
              placeholder={t('كلمة مرور مؤقتة جديدة', 'New temporary password')}
            />
            <button
              className="btn btn-danger"
              disabled={busy || password.length === 0}
              onClick={() =>
                run(
                  'reset',
                  () => api.resetUserPassword(user.id, password, reason.trim()),
                  t('أُعيد التعيين وأُبطلت الجلسات', 'Password reset and sessions revoked'),
                )
              }
            >
              <KeyRound size={15} /> {t('إعادة تعيين', 'Reset')}
            </button>
          </div>
        </Field>
      </div>
    </Modal>
  );
}
