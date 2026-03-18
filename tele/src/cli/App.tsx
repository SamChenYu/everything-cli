import React, { useState, useEffect, useRef } from "react";
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
  const telegramRef = useRef<TelegramService | null>(null);
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
        telegramRef.current = tg;

        await tg.connect();
        setStage("loading_chats");

        const recentChats = await tg.getRecentChats(10);
        setChats(recentChats);
        setStage("selecting_chat");
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setStage("error");
      }
    };

    init();

    return () => {
      const currentTelegram = telegramRef.current;
      if (currentTelegram) {
        currentTelegram.unsubscribeFromNewMessages();
        currentTelegram.disconnect();
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
      } else if (char >= "0" && char <= "9") {
        const index = char === "0" ? 9 : parseInt(char) - 1;
        const chat = chats[index];
        if (chat) {
          loadMessages(chat);
        }
      }
    } else if (stage === "viewing_messages") {
      if (key.return) {
        if (input.trim() === ":q") {
          // Go back to chat selection
          telegram?.unsubscribeFromNewMessages();
          setSelectedChat(null);
          setMessages([]);
          setInput("");
          setStage("selecting_chat");
        } else if (input.trim() !== "") {
          // Send message
          sendMessage(input);
        }
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

      telegram.subscribeToNewMessages(chat.id, (newMsg) => {
        setMessages((prev) => [...prev, newMsg]);
      });
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
      const sentMessage = await telegram.sendMessage(selectedChat.id, text);
      setMessages((prev) => [...prev, sentMessage]);
      setInput("");
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
        <Text color="green">Connecting to Telegram...</Text>
      </Box>
    );
  }

  if (stage === "loading_chats") {
    return (
      <Box flexDirection="column">
        <Text color="green">Loading recent chats...</Text>
      </Box>
    );
  }

  if (stage === "error") {
    return (
      <Box flexDirection="column">
        <Text color="red">Error: {error}</Text>
        <Text color="green">Press Ctrl+C to exit</Text>
      </Box>
    );
  }

  if (stage === "selecting_chat") {
    return (
      <Box flexDirection="column">
        <Text color="green" bold>
          Select a chat (use arrow keys or press 1-9, 0 for 10):
        </Text>
        <Text> </Text>
        {chats.map((chat, index) => (
          <Box key={chat.id}>
            <Text color="green" bold={index === selectedChatIndex}>
              {index === selectedChatIndex ? "> " : "  "}
              {index + 1}. {chat.title} ({chat.type})
            </Text>
          </Box>
        ))}
        <Text> </Text>
        <Text color="green">Press Enter to select, Ctrl+C to exit</Text>
      </Box>
    );
  }

  if (stage === "loading_messages") {
    return (
      <Box flexDirection="column">
        <Text color="green">Loading messages from {selectedChat?.title}...</Text>
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
          <Box key={msg.id} flexDirection="column" marginBottom={0}>
            <Text color="green">
              [{msg.date.toLocaleString()}] {msg.senderName}: {msg.text}
            </Text>
          </Box>
        ))}
        <Text> </Text>
        <Box borderStyle="single" borderColor="green" paddingX={1}>
          <Text color="green">
            {isSending ? "Sending..." : `> ${input}`}
          </Text>
        </Box>
        <Text> </Text>
        <Text color="green">Type to compose, Enter to send, ':q' + Enter to go back, Ctrl+C to exit</Text>
      </Box>
    );
  }

  return null;
}
