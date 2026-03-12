import React, { useState } from "react";
import { Box, Text, useInput, useApp } from "ink";

export default function App() {
  const [input, setInput] = useState("");
  const { exit } = useApp();

  useInput((char, key) => {
    if (key.return) {
      console.log("Send:", input);
      setInput("");
    } else if (key.backspace || key.delete) {
      // remove last character
      setInput(prev => prev.slice(0, -1));
    } else if (key.ctrl && char === "c") {
      // exit on Ctrl+C
      exit();
    } else if (!key.ctrl && !key.meta) {
      // append normal character
      setInput(prev => prev + char);
    }
  });

  return (
    <Box flexDirection="column">
      <Text color="green"></Text>
      <Text>{"> " + input}</Text>
    </Box>
  );
}