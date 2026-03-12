import { TelegramClient } from "telegram";
import { StringSession } from "telegram/sessions/index.js";
import { Api } from "telegram";

export interface Chat {
  id: string;
  title: string;
  type: string;
}

export interface Message {
  id: number;
  text: string;
  date: Date;
  senderId?: string;
  senderName?: string;
}

export class TelegramService {
  private client: TelegramClient | null = null;
  private apiId: number;
  private stringSession: string;

  constructor(apiId: string, stringSession: string) {
    this.apiId = parseInt(apiId);
    this.stringSession = stringSession;
  }

  async connect(): Promise<void> {
    const session = new StringSession(this.stringSession);
    this.client = new TelegramClient(session, this.apiId, "", {
      connectionRetries: 5,
    });

    await this.client.connect();
  }

  async getRecentChats(limit: number = 5): Promise<Chat[]> {
    if (!this.client) {
      throw new Error("Client not connected");
    }

    const dialogs = await this.client.getDialogs({ limit });

    return dialogs.map((dialog) => {
      const entity = dialog.entity;
      let title = "Unknown";
      let type = "unknown";

      if (entity instanceof Api.User) {
        title = entity.firstName || "";
        if (entity.lastName) {
          title += ` ${entity.lastName}`;
        }
        if (!title.trim()) {
          title = `User ${entity.id}`;
        }
        type = "user";
      } else if (entity instanceof Api.Chat) {
        title = entity.title;
        type = "chat";
      } else if (entity instanceof Api.Channel) {
        title = entity.title;
        type = entity.broadcast ? "channel" : "group";
      }

      return {
        id: dialog.id?.toString() || "",
        title,
        type,
      };
    });
  }

  async getMessages(chatId: string, limit: number = 10): Promise<Message[]> {
    if (!this.client) {
      throw new Error("Client not connected");
    }

    const messages = await this.client.getMessages(chatId, { limit });

    return messages.map((msg) => {
      let senderName = "Unknown";

      if (msg.sender && msg.sender instanceof Api.User) {
        senderName = msg.sender.firstName || "";
        if (msg.sender.lastName) {
          senderName += ` ${msg.sender.lastName}`;
        }
        if (!senderName.trim()) {
          senderName = `User ${msg.sender.id}`;
        }
      }

      return {
        id: msg.id,
        text: msg.text || "(no text)",
        date: new Date(msg.date * 1000),
        senderId: msg.senderId?.toString(),
        senderName,
      };
    });
  }

  async disconnect(): Promise<void> {
    if (this.client) {
      await this.client.disconnect();
      this.client = null;
    }
  }
}
