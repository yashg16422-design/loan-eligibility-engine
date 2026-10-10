-- 009_account_admin.sql: admin belongs to the person (the account), not to one sign-in method.
--
-- Cognito groups are per Cognito user, and a Google sign-in is a separate Cognito user from the
-- email+password one even for the same address. The api Lambda copies a Cognito `admin` group
-- membership onto the account row the first time it sees it, so every sign-in method that
-- resolves to that account (one row per verified email) carries admin from then on.
ALTER TABLE accounts ADD COLUMN is_admin boolean NOT NULL DEFAULT false;
