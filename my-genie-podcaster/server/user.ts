/**
 * Per-request user identity + on-behalf-of (OBO) Databricks client.
 *
 * Databricks Apps forward the signed-in user's identity and access token via
 * `x-forwarded-*` headers. We build a WorkspaceClient from that token so Genie
 * queries run as the user (their own permissions apply), and we use the user id
 * to scope podcasts to their owner.
 *
 * In local development there is no forwarding proxy, so we fall back to the
 * service-principal client and a fixed local owner id.
 */
import type { Request } from 'express';
import { getExecutionContext } from '@databricks/appkit';
import { WorkspaceClient } from '@databricks/sdk-experimental';

export interface RequestUser {
  /** Databricks client scoped to the user (OBO) — or the service client in dev. */
  client: WorkspaceClient;
  /** Stable owner identifier used to scope stored podcasts. */
  id: string;
  email?: string;
}

const DEV_OWNER_ID = process.env.DEV_USER_ID ?? 'local-dev';

export function requestUser(req: Request): RequestUser {
  const token = req.header('x-forwarded-access-token');
  const email = req.header('x-forwarded-email');
  const forwardedUser = req.header('x-forwarded-user');

  if (token) {
    const host = process.env.DATABRICKS_HOST ?? getExecutionContext().client.config.host;
    return {
      // Pin to PAT/token auth: the app SP's OAuth M2M env vars
      // (DATABRICKS_CLIENT_ID/SECRET, injected once Lakebase was added) would
      // otherwise collide with this user token — "more than one authorization
      // method configured: oauth and pat".
      client: new WorkspaceClient({ host, token, authType: 'pat' }),
      id: forwardedUser ?? email ?? 'user',
      email,
    };
  }

  // Local dev: no OBO token available — use the service principal.
  return {
    client: getExecutionContext().client,
    id: forwardedUser ?? email ?? DEV_OWNER_ID,
    email: email ?? process.env.DEV_USER_EMAIL,
  };
}
