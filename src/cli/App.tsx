import React, { useState, useEffect } from "react";
import { Box, Text, useInput, useApp } from "ink";
import { TelegramService } from "../telegram/TelegramService.js";
import type { Chat, Message } from "../telegram/TelegramService.js";

type Stage = "connecting" | "loading_chats" | "selecting_chat" | "loading_messages" | "viewing_messages" | "error";

export default function App() {
  const [stage, setStage] = useState<Stage>("connecting");
  const [chats, setChats] = useState<Chat[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [selectedChatIndex, setSelectedChatIndex] = useState(0);
  const [selectedChat, setSelectedChat] = useState<Chat | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [telegram, setTelegram] = useState<TelegramService | null>(null);
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const { exit } = useApp();

  useEffect(() => {
    const init = async () => {
      try {
        const apiId = process.env.TELEGRAM_API_ID;
        const apiHash = process.env.TELEGRAM_API_HASH;
        const stringSession = process.env.TELEGRAM_STRING_SESSION;

        if (!apiId) {
          setError("Missing TELEGRAM_API_ID in .env file");
          setStage("error");
          return;
        }

        if (!apiHash) {
          setError("Missing TELEGRAM_API_HASH in .env file");
          setStage("error");
          return;
        }

        if (!stringSession) {
          setError("Missing TELEGRAM_STRING_SESSION in .env file");
          setStage("error");
          return;
        }

        const tg = new TelegramService(apiId, apiHash, stringSession);
        setTelegram(tg);

        await tg.connect();
        setStage("loading_chats");

        const recentChats = await tg.getRecentChats(5);
        setChats(recentChats);
        setStage("selecting_chat");
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setStage("error");
      }
    };

    init();

    return () => {
      if (telegram) {
        telegram.disconnect();
      }
    };
  }, []);

  useInput((char, key) => {
    if (key.ctrl && char === "c") {
      exit();
      return;
    }

    if (stage === "selecting_chat") {
      if (key.upArrow) {
        setSelectedChatIndex((prev) => Math.max(0, prev - 1));
      } else if (key.downArrow) {
        setSelectedChatIndex((prev) => Math.min(chats.length - 1, prev + 1));
      } else if (key.return) {
        const chat = chats[selectedChatIndex];
        if (chat) {
          loadMessages(chat);
        }
      } else if (char >= "1" && char <= "5") {
        const index = parseInt(char) - 1;
        const chat = chats[index];
        if (chat) {
          loadMessages(chat);
        }
      }
    } else if (stage === "viewing_messages") {
      if (char === "b" && !key.ctrl && !key.meta && input.length === 0) {
        // Go back to chat selection (only if input is empty)
        setSelectedChat(null);
        setMessages([]);
        setInput("");
        setStage("selecting_chat");
      } else if (key.return && input.trim() !== "") {
        // Send message
        sendMessage(input);
      } else if (key.backspace || key.delete) {
        // Remove last character
        setInput((prev) => prev.slice(0, -1));
      } else if (!key.ctrl && !key.meta && !key.escape) {
        // Append normal character
        setInput((prev) => prev + char);
      }
    }
  });

  const loadMessages = async (chat: Chat) => {
    setSelectedChat(chat);
    setStage("loading_messages");

    try {
      if (!telegram) {
        throw new Error("Telegram not initialized");
      }

      const msgs = await telegram.getMessages(chat.id, 10);
      setMessages(msgs.reverse());
      setStage("viewing_messages");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStage("error");
    }
  };

  const sendMessage = async (text: string) => {
    if (!telegram || !selectedChat || isSending) {
      return;
    }

    setIsSending(true);

    try {
      await telegram.sendMessage(selectedChat.id, text);
      setInput("");

      // Reload messages to show the sent message
      const msgs = await telegram.getMessages(selectedChat.id, 10);
      setMessages(msgs.reverse());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStage("error");
    } finally {
      setIsSending(false);
    }
  };

  if (stage === "connecting") {
    return (
      <Box flexDirection="column">
        <Text color="cyan">Connecting to Telegram...</Text>
      </Box>
    );
  }

  if (stage === "loading_chats") {
    return (
      <Box flexDirection="column">
        <Text color="cyan">Loading recent chats...</Text>
      </Box>
    );
  }

  if (stage === "error") {
    return (
      <Box flexDirection="column">
        <Text color="red">Error: {error}</Text>
        <Text color="gray">Press Ctrl+C to exit</Text>
      </Box>
    );
  }

  if (stage === "selecting_chat") {
    return (
      <Box flexDirection="column">
        <Text color="green" bold>
          Select a chat (use arrow keys or press 1-5):
        </Text>
        <Text> </Text>
        {chats.map((chat, index) => (
          <Box key={chat.id}>
            <Text color={index === selectedChatIndex ? "cyan" : "white"}>
              {index === selectedChatIndex ? "> " : "  "}
              {index + 1}. {chat.title} ({chat.type})
            </Text>
          </Box>
        ))}
        <Text> </Text>
        <Text color="gray">Press Enter to select, Ctrl+C to exit</Text>
      </Box>
    );
  }

  if (stage === "loading_messages") {
    return (
      <Box flexDirection="column">
        <Text color="cyan">Loading messages from {selectedChat?.title}...</Text>
      </Box>
    );
  }

  if (stage === "viewing_messages") {
    return (
      <Box flexDirection="column">
        <Text color="green" bold>
          Messages from: {selectedChat?.title}
        </Text>
        <Text> </Text>
        {messages.map((msg) => (
          <Box key={msg.id} flexDirection="column" marginBottom={1}>
            <Text color="yellow">
              [{msg.date.toLocaleString()}] {msg.senderName}:
            </Text>
            <Text>{msg.text}</Text>
          </Box>
        ))}
        <Text> </Text>
        <Box borderStyle="single" borderColor="cyan" paddingX={1}>
          <Text>
            {isSending ? "Sending..." : `> ${input}`}
          </Text>
        </Box>
        <Text> </Text>
        <Text color="gray">Type to compose, Enter to send, 'b' (when empty) to go back, Ctrl+C to exit</Text>
      </Box>
    );
  }

  return null;
}