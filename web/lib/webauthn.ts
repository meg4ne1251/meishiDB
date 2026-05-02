"use client";

import {
  startAuthentication,
  startRegistration,
} from "@simplewebauthn/browser";

import { webauthnApi } from "@/lib/api";

export async function registerPasskey(nickname?: string) {
  const { challenge_id, options } = await webauthnApi.registerBegin();
  // @simplewebauthn/browser v11+ は { optionsJSON } 形式を期待する
  const credential = await startRegistration({ optionsJSON: options as any });
  return webauthnApi.registerFinish({ challenge_id, credential, nickname });
}

export async function loginWithPasskey(email?: string) {
  const { challenge_id, options } = await webauthnApi.loginBegin(email);
  const credential = await startAuthentication({ optionsJSON: options as any });
  return webauthnApi.loginFinish({ challenge_id, credential });
}
