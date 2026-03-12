import React, { useState } from "react";
import { Box, Text, useInput } from "ink";

export default function App() {
  const [input, setInput] = useState("");

  useInput((char, key) => {
    if (key.return) {
      console.log("Send:", input);
      setInput("");
    } else {
      setInput(prev => prev + char);
    }
  });

  return (
    <Box flexDirection="column">
      <Text>CLI Messenger</Text>
      <Text>{"> " + input}</Text>
    </Box>
  );
}