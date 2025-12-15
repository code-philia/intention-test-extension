import { Chat } from '@douyinfe/semi-ui';
import '@douyinfe/semi-ui/dist/css/semi.min.css';
import type { Message, RoleConfig } from '@douyinfe/semi-ui/lib/es/chat/interface';
import 'prismjs/plugins/autoloader/prism-autoloader.min.js';
import 'prismjs/themes/prism-tomorrow.min.css';
import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';
import './App.css';
import testLogo from './assets/test-tube.svg';

// DEBUG
// const defaultMessage: Message[] = [
//   {
//     role: 'system',
//     id: '1',
//     createAt: 1715676751919,
//     content: "Hello, I'm IntentionTest, an LLM based Java test generator.",
//   },
//   {
//     role: 'user',
//     id: '2',
//     createAt: 1715676751919,
//     content: "Generate test for the constructor of Message",
//   },
//   {
//     role: 'assistant',
//     id: '3',
//     createAt: 1715676751919,
//     content:
//       `Here is your test:

// \`\`\`java
// public class AppTest {
//     @Test
//     public void testMessageHandling() {
//         // Test message creation
//         Message message = new Message();
//         message.setRole("user");
//         message.setContent("test content");
//         assertNotNull(message.getId());
//         assertTrue(message.getCreateAt() > 0);
        
//         // Test role configuration
//         assertEquals("User", roleInfo.get("user").getName());
//         assertEquals("Assistant", roleInfo.get("assistant").getName());
//         assertEquals("System", roleInfo.get("system").getName());
//     }
// }
// \`\`\``
//   }
// ];

const defaultMessage: Message[] = [];

const roleConfig: RoleConfig = {
  user: {
    name: 'User',
  },
  assistant: {
    name: 'Assistant',
  },
  system: {
    name: 'System',
  }
};


// Declare the VS Code API on the Window object
declare global {
  interface Window {
    acquireVsCodeApi?: () => { postMessage: (msg: unknown) => void };
  }
}

// Counter for generating unique message IDs
let idCounter = 0;
function getId() {
  return `id-${++idCounter}`;
}

function App() {
  const [messages, setMessages] = useState<Message[]>(defaultMessage);

  // Helper to add a new message to the state
  const addMessage = useCallback((msg: Message) => {
    setMessages(prev => [...prev, msg]);
  }, []);

  // Helper to remove any typing animation messages
  const removeTypingMessage = useCallback(() => {
    setMessages(prev => prev.filter(m => m.role ? !m.role.endsWith('-wait') : true));
  }, []);

  // DEBUG
  // useEffect(() => {
  //   if (messages.length < 20) {
  //     const addNewMessageTimeout = setTimeout(() => {
  //       setMessages([...messages, messages[0]])
  //     }, 2000);
  //     return () => clearTimeout(addNewMessageTimeout);
  //   }
  // }, [messages])

  const lastRequestAnimationFrame: RefObject<number | undefined> = useRef(undefined);

  // Custom smooth scroll with bezier curve animation
  const smoothScrollToBottom = useCallback(() => {
    if (lastRequestAnimationFrame.current !== undefined) {
      cancelAnimationFrame(lastRequestAnimationFrame.current);
    }
    
    const animateScroll = () => {
      const startY = document.documentElement.scrollTop;
      const targetY = document.documentElement.scrollHeight - document.documentElement.clientHeight;
      const distance = targetY - startY;

      if (distance <= 10) return;

      const currentY = startY + (Math.min(distance, Math.max(distance * 0.1, 10)));
      document.documentElement.scrollTo(0, currentY);
      
      if (currentY < targetY) {
        lastRequestAnimationFrame.current = requestAnimationFrame(animateScroll);
      }
    };
    
    lastRequestAnimationFrame.current = requestAnimationFrame(animateScroll);
  }, []);

  useEffect(() => {
    smoothScrollToBottom();
  }, [messages, smoothScrollToBottom])

  // Listen for messages from the window (similar to index.js logic)
  useEffect(() => {
    const messageHandler = (event: MessageEvent) => {
      const msg = event.data;
      console.log('Extension message:', msg);
      if (msg && msg.role && msg.content) {
        if (msg.role.endsWith('-wait')) {
          // When role ends with '-wait', show typing animation
          const role = msg.role.slice(0, -5);
          setMessages(prev => {
            if (prev.find(m => m.role === `${role}-wait`)) return prev;
            return [...prev, { role: `${role}-wait`, id: msg.id || getId(), createAt: Date.now(), status: 'loading' }];
          });
        } else {
          // Remove typing message if present and display the actual message
          removeTypingMessage();
          // Use the message ID from server if available, otherwise generate one
          const messageId = msg.id || getId();
          
          // Check if message with this ID already exists to prevent duplicates
          setMessages(prev => {
            const existingMessage = prev.find(m => m.id === messageId);
            if (existingMessage) {
              // Only update existing message if content has actually changed
              if (existingMessage.content !== msg.content) {
                return prev.map(m => m.id === messageId 
                  ? { ...msg, createAt: Date.now() }
                  : m
                );
              }
              // Content is the same, no update needed
              return prev;
            } else {
              // Add new message
              return [...prev, { role: msg.role, content: msg.content, id: messageId, createAt: Date.now() }];
            }
          });
        }
      }
    };

    window.addEventListener('message', messageHandler);
    return () => window.removeEventListener('message', messageHandler);
  }, [addMessage, removeTypingMessage]);

  // Handle sending a message from the chat UI
  const onMessageSend = useCallback((content: string) => {
    const userMsg: Message = { role: 'user', content, id: getId(), createAt: Date.now() };
    addMessage(userMsg);
    const vscode = window.acquireVsCodeApi ? window.acquireVsCodeApi() : null;
    if (vscode) {
      vscode.postMessage({ cmd: 'send', content });
    }
  }, [addMessage]);

  console.log('Rendering with messages:', messages);

  return (
    <div>
      {messages.length === 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginTop: '50px' }}>
          <img src={testLogo} alt="Test Tube" style={{ width: '100px', height: '100px' }} />
          <h2 style={{ fontWeight: 'bold', margin: '0.3rem' }}>
            IntentionTest
          </h2>
          <div style={{ width: '18rem', fontSize: '0.8rem', textAlign: 'center' }}>Try generating a test, and the chat will be here.</div>
        </div>
      )}
      <Chat
        chats={messages}
        roleConfig={roleConfig}
        onMessageSend={onMessageSend}
        renderInputArea={() => undefined}
        chatBoxRenderConfig={{
          renderChatBoxAvatar: () => undefined
        }}
      />
    </div>
  );
}

export default App;
