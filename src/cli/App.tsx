import React, { useState, useEffect } from "react";
import { Box, Text, useInput, useApp } from "ink";
import { TelegramService, Chat, Message } from "../telegram/TelegramService.js";

type Stage = "connecting" | "loading_chats" | "selecting_chat" | "loading_messages" | "viewing_messages" | "error";

export default function App() {
  const [stage, setStage] = useState<Stage>("connecting");
  const [chats, setChats] = useState<Chat[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [selectedChatIndex, setSelectedChatIndex] = useState(0);
  const [selectedChat, setSelectedChat] = useState<Chat | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [telegram, setTelegram] = useState<TelegramService | null>(null);
  const { exit } = useApp();

  useEffect(() => {
    const init = async () => {
      try {
        const apiId = process.env.TELEGRAM_API_ID;
        const stringSession = process.env.TELEGRAM_STRING_SESSION;

        if (!apiId || !stringSession) {
          setError("Missing TELEGRAM_API_ID or TELEGRAM_STRING_SESSION in .env file");
          setStage("error");
          return;
        }

        const tg = new TelegramService(apiId, stringSession);
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
        loadMessages(chats[selectedChatIndex]);
      } else if (char >= "1" && char <= "5") {
        const index = parseInt(char) - 1;
        if (index < chats.length) {
          loadMessages(chats[index]);
        }
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
        <Text color="gray">Press Ctrl+C to exit</Text>
      </Box>
    );
  }

  return null;
}