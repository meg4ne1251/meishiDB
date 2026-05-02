export type CardStatus =
  | "uploaded"
  | "ocr_running"
  | "ocr_done"
  | "confirmed"
  | "archived";

export type CardSource = "upload" | "camera" | "scanner" | "manual" | "email";

export interface CardFields {
  person_name: string | null;
  person_name_kana: string | null;
  company: string | null;
  department: string | null;
  title: string | null;
  postal_code: string | null;
  address: string | null;
  phone: string | null;
  mobile: string | null;
  fax: string | null;
  email: string | null;
  website: string | null;
}

export interface CardFieldsRead extends CardFields {
  raw_ocr_text: string | null;
  ocr_confidence: Record<string, number> | null;
}

export interface Tag {
  id: string;
  name: string;
  color: string | null;
  created_at?: string;
}

export interface Card {
  id: string;
  owner_id: string;
  status: CardStatus;
  source: CardSource;
  image_front_key: string | null;
  image_back_key: string | null;
  created_at: string;
  updated_at: string;
  fields: CardFieldsRead | null;
  tags: Tag[];
  is_favorite: boolean;
  shared: boolean;
}

export interface PasskeyCredential {
  id: string;
  nickname: string | null;
  created_at: string;
  last_used_at: string | null;
}

export interface CardListResponse {
  items: Card[];
  total: number;
}

export interface CurrentUser {
  id: string;
  email: string;
  display_name: string;
  role: "admin" | "member";
}

export interface ShareInfo {
  id: string;
  card_id: string;
  shared_by: string;
  shared_with: string;
  permission: "view" | "edit";
  created_at: string;
}

export interface UserSummary {
  id: string;
  email: string;
  display_name: string;
  role: "admin" | "member";
}
