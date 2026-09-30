export interface SourceDocument {
  page_id: string;
  title: string;
  url: string;
  space_key: string;
  space_name: string;
  excerpt: string;
  score: number;
  last_modified?: string | null;
}

/** Derived source type based on space_key prefix */
export type SourceType = 'confluence' | 'jira' | 'github' | 'upload';

export function getSourceType(source: SourceDocument): SourceType {
  if (source.space_key === '__JIRA__') return 'jira';
  if (source.space_key === '__GITHUB__') return 'github';
  if (source.space_key === '__UPLOAD__') return 'upload';
  return 'confluence';
}

export type MessageRole = 'user' | 'assistant';
export type MessageStatus = 'streaming' | 'complete' | 'error';
export type FeedbackValue = 1 | -1 | null;
export type NegativeFeedbackReason = 'outdated_information' | 'wrong_answer' | 'incomplete_answer' | 'not_relevant' | 'other';

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  sources?: SourceDocument[];
  confidence?: string;
  confidenceScore?: number;
  status: MessageStatus;
  timestamp: Date;
  feedback?: FeedbackValue;
}

export interface ChatState {
  messages: ChatMessage[];
  isLoading: boolean;
  conversationId: string | null;
  error: string | null;
  correctedQuery: { original: string; corrected: string } | null;
  selectedSpaces: string[];
  streamStatus: string | null;
}

export interface QueryCorrectedEvent {
  original: string;
  corrected: string;
}

export interface StreamTokenEvent {
  text: string;
  conversation_id: string;
  assistant_msg_id?: string;
}

export type SSEEventType = 'token' | 'sources' | 'error' | 'done';

export interface ConversationSummary {
  id: string;
  title: string;
  preview: string;
  createdAt: string;
  updatedAt: string;
  folderId?: string | null;
}

export interface ConversationFolder {
  id: string;
  name: string;
  createdAt: string;
}

export interface UploadedFile {
  upload_id: string;
  filename: string;
  chunks: number;
}
