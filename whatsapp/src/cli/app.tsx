import React, { useState, useEffect, useRef, useCallback } from "react";
import { Box, Text, useInput, useApp } from "ink";
import { WhatsAppService } from "../whatsapp/WhatsAppService.js";
import type { Chat, Message } from "../whatsapp/WhatsAppService.js";

const VISIBLE_CHATS = 10;
const RECENT_CHATS_LIMIT = 25;
const MESSAGE_LIMIT = 10;
const POLL_INTERVAL_MS = 1_000;

type Stage =
  | "launching"
  | "waiting_for_qr"
  | "loading_chats"
  | "selecting_chat"
  | "loading_messages"
  | "viewing_messages"
  | "error";

export default function App() {
  const [stage, setStage] = useState<Stage>("launching");
  const [chats, setChats] = useState<Chat[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [selectedChatIndex, setSelectedChatIndex] = useState(0);
  const [scrollOffset, setScrollOffset] = useState(0);
  const [selectedChat, setSelectedChat] = useState<Chat | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [whatsapp] = useState<WhatsAppService>(() => new WhatsAppService());
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const { exit } = useApp();

  useEffect(() => {
    const init = async () => {
      try {
        await whatsapp.launch();

        await whatsapp.waitForQROrLogin(() => {
          setStage("waiting_for_qr");
        });

        setStage("loading_chats");
        const recentChats = await whatsapp.getRecentChats(RECENT_CHATS_LIMIT);
        setChats(recentChats);
        setStage("selecting_chat");
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setStage("error");
      }
    };

    init();

    return () => {
      whatsapp.close().catch(() => {});
    };
  }, []);

  useInput((char, key) => {
    if (key.ctrl && char === "c") {
      whatsapp.close().finally(() => exit());
      return;
    }

    if (stage === "selecting_chat") {
      // If there are no chats, ignore navigation and selection input.
      if (chats.length === 0) {
        return;
      }

      if (key.upArrow) {
        setSelectedChatIndex((prev) => {
          const next = Math.max(0, prev - 1);
          setScrollOffset((off) => (next < off ? next : off));
          return next;
        });
      } else if (key.downArrow) {
        setSelectedChatIndex((prev) => {
          const next = Math.min(chats.length - 1, prev + 1);
          setScrollOffset((off) => (next >= off + VISIBLE_CHATS ? next - VISIBLE_CHATS + 1 : off));
          return next;
        });
      } else if (key.return) {
        const chat = chats[selectedChatIndex];
        if (chat) {
          loadMessages(selectedChatIndex, chat);
        }
      }
    } else if (stage === "viewing_messages") {
      if (key.return) {
        if (input.trim() === ":q") {
          stopPolling();
          setSelectedChat(null);
          setMessages([]);
          setInput("");
          setStage("selecting_chat");
        } else if (input.trim() !== "") {
          sendMessage(input);
        }
      } else if (key.backspace || key.delete) {
        setInput((prev) => prev.slice(0, -1));
      } else if (!key.ctrl && !key.meta && !key.escape) {
        setInput((prev) => prev + char);
      }
    }
  });

  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const isPollingRef = useRef(false);

  const pollMessages = useCallback(async () => {
    if (isPollingRef.current) return;
    isPollingRef.current = true;
    try {
      const msgs = await whatsapp.getMessages(MESSAGE_LIMIT);
      setMessages(msgs);
    } catch {
      // Silently ignore polling errors to avoid disrupting the UI
    } finally {
      isPollingRef.current = false;
    }
  }, [whatsapp]);

  const startPolling = useCallback(() => {
    stopPolling();
    pollingRef.current = setInterval(pollMessages, POLL_INTERVAL_MS);
  }, [pollMessages]);

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  useEffect(() => () => stopPolling(), [stopPolling]);

  const loadMessages = async (chatIndex: number, chat: Chat) => {
    setSelectedChat(chat);
    setStage("loading_messages");

    try {
      await whatsapp.openChat(chatIndex);
      const msgs = await whatsapp.getMessages(MESSAGE_LIMIT);
      setMessages(msgs);
      setStage("viewing_messages");
      startPolling();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStage("error");
    }
  };

  const sendMessage = async (text: string) => {
    if (isSending) return;
    setIsSending(true);

    try {
      await whatsapp.sendMessage(text);
      setInput("");
      const msgs = await whatsapp.getMessages(MESSAGE_LIMIT);
      setMessages(msgs);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStage("error");
    } finally {
      setIsSending(false);
    }
  };

  if (stage === "launching") {
    return (
      <Box flexDirection="column">
        <Text color="green">Launching WhatsApp Web in Chromium...</Text>
      </Box>
    );
  }

  if (stage === "waiting_for_qr") {
    return (
      <Box flexDirection="column">
        <Text color="green" bold>
          WhatsApp Web – Scan QR Code
        </Text>
        <Text> </Text>
        <Text color="yellow">
          A Chromium browser window has opened. Please scan the QR code with your phone to log in.
        </Text>
        <Text color="green">Waiting for login...</Text>
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
    const visibleChats = chats.slice(scrollOffset, scrollOffset + VISIBLE_CHATS);
    const hasMoreAbove = scrollOffset > 0;
    const hasMoreBelow = scrollOffset + VISIBLE_CHATS < chats.length;

    return (
      <Box flexDirection="column">
        <Text color="green" bold>
          Select a chat ({chats.length} chats):
        </Text>
        <Text> </Text>
        {hasMoreAbove && <Text color="green" dimColor>  ↑ more chats above</Text>}
        {visibleChats.map((chat, i) => {
          const index = scrollOffset + i;
          return (
            <Box key={chat.id}>
              <Text color="green" bold={index === selectedChatIndex}>
                {index === selectedChatIndex ? "> " : "  "}
                {index + 1}. {chat.title}
              </Text>
            </Box>
          );
        })}
        {hasMoreBelow && <Text color="green" dimColor>  ↓ more chats below</Text>}
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
        {messages.map((msg, i) => (
          <Box key={msg.id || i} flexDirection="column" marginBottom={0}>
            <Text color={msg.isFromMe ? "cyan" : "green"}>
              [{msg.date.toLocaleTimeString()}] {msg.senderName}: {msg.text}
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
        <Text color="green">
          Type to compose, Enter to send, ':q' + Enter to go back, Ctrl+C to exit
        </Text>
      </Box>
    );
  }

  return null;
}
