/**
 * QA-Agent Midscene Executor
 * 
 * Node.js process that receives commands from Python via stdin,
 * executes them using Midscene.js/Playwright, and returns results via stdout.
 * 
 * Communication Protocol:
 * - Input: JSON objects, one per line
 * - Output: JSON objects, one per line
 * 
 * Commands:
 * - launch: Open browser and navigate to URL
 * - screenshot: Take screenshot
 * - aiAction: Execute natural language action via Midscene
 * - aiBoolean: Ask yes/no question via Midscene
 * - keyboard: Press keyboard keys
 * - type: Type text
 * - goto: Navigate to URL
 * - close: Close browser
 */

import { chromium, firefox, webkit } from 'playwright';
import { PlaywrightAgent } from '@midscene/web/playwright';
import readline from 'readline';

// Configure Midscene to use local Ollama
// Ollama provides OpenAI-compatible API at /v1
process.env.MIDSCENE_MODEL_NAME = process.env.MIDSCENE_MODEL_NAME || 'glm-ocr';
process.env.MIDSCENE_MODEL_BASE_URL = process.env.MIDSCENE_MODEL_BASE_URL || 'http://localhost:11434/v1';
process.env.MIDSCENE_MODEL_FAMILY = process.env.MIDSCENE_MODEL_FAMILY || 'glm-v';

// Browser and Midscene agent instances
let browser = null;
let page = null;
let aiAgent = null;

// Output JSON to stdout (protocol channel)
function output(data) {
    process.stdout.write(JSON.stringify(data) + '\n');
}

// Debug logging to stderr (doesn't interfere with JSON protocol)
function logDebug(message, ...args) {
    console.error('[executor]', message, ...args);
}

// Error logging to stderr with full context
function logError(context, error) {
    console.error(`[${context}] ${error.message || error}`);
    if (error.stack) {
        console.error(error.stack);
    }
}

// Initialize Midscene AI agent
async function initAiAgent() {
    if (!page) return null;
    
    try {
        // Create PlaywrightAgent instance from page
        aiAgent = new PlaywrightAgent(page);
        return aiAgent;
    } catch (error) {
        logDebug('Failed to initialize AI agent:', error.message);
        return null;
    }
}

// Command handlers
const handlers = {
    async launch({ url, config = {} }) {
        try {
            const browserType = config.browser === 'firefox' ? firefox 
                              : config.browser === 'webkit' ? webkit 
                              : chromium;
            
            browser = await browserType.launch({
                headless: config.headless ?? true,
            });
            
            page = await browser.newPage({
                viewport: config.viewport || { width: 1920, height: 1080 },
            });
            
            await page.goto(url, { waitUntil: 'networkidle' });
            
            // Initialize AI agent after page is ready
            await initAiAgent();
            
            output({ success: true, url });
        } catch (error) {
            logError('launch', error);
            output({ success: false, error: error.message });
        }
    },

    async screenshot({ path }) {
        try {
            if (!page) throw new Error('No page open');
            await page.screenshot({ path, fullPage: false });
            output({ success: true, path });
        } catch (error) {
            logError('screenshot', error);
            output({ success: false, error: error.message });
        }
    },

    async aiAction({ instruction }) {
        try {
            if (!page) throw new Error('No page open');
            
            if (aiAgent) {
                // Use Midscene AI action
                await aiAgent.aiAction(instruction);
                output({ success: true, action: 'aiAction', instruction });
                return;
            }
            
            // Fallback to simple Playwright locator
            const clickMatch = instruction.match(/click (?:on |the )?['"]?([^'"]+)['"]?/i);
            if (clickMatch) {
                const target = clickMatch[1].trim();
                // Try multiple strategies
                try {
                    await page.getByRole('button', { name: target }).first().click({ timeout: 5000 });
                } catch {
                    try {
                        await page.getByText(target, { exact: false }).first().click({ timeout: 5000 });
                    } catch {
                        await page.locator(`text=${target}`).first().click({ timeout: 5000 });
                    }
                }
                output({ success: true, action: 'click', target });
                return;
            }
            
            const typeMatch = instruction.match(/type ['"](.+)['"]/i);
            if (typeMatch) {
                const text = typeMatch[1];
                await page.keyboard.type(text);
                output({ success: true, action: 'type', text });
                return;
            }
            
            output({ success: false, error: `Could not parse instruction: ${instruction}` });
        } catch (error) {
            logError('aiAction', error);
            output({ success: false, error: error.message });
        }
    },

    async aiBoolean({ question }) {
        try {
            if (!page) throw new Error('No page open');
            
            if (aiAgent) {
                // Use Midscene AI boolean
                const result = await aiAgent.aiBoolean(question);
                output({ success: true, result, question });
                return;
            }
            
            // Fallback: can't answer without AI
            output({ success: false, error: 'AI agent not available for aiBoolean' });
        } catch (error) {
            logError('aiBoolean', error);
            output({ success: false, error: error.message });
        }
    },

    async aiQuery({ query }) {
        try {
            if (!page) throw new Error('No page open');
            
            if (aiAgent) {
                // Use Midscene AI query
                const result = await aiAgent.aiQuery(query);
                output({ success: true, result, query });
                return;
            }
            
            output({ success: false, error: 'AI agent not available for aiQuery' });
        } catch (error) {
            logError('aiQuery', error);
            output({ success: false, error: error.message });
        }
    },

    async keyboard({ keys }) {
        try {
            if (!page) throw new Error('No page open');
            
            // Parse key combination (e.g., "ctrl+o" -> Control+o)
            const keyMap = {
                'ctrl': 'Control',
                'alt': 'Alt',
                'shift': 'Shift',
                'meta': 'Meta',
                'cmd': 'Meta',
                'enter': 'Enter',
                'escape': 'Escape',
                'esc': 'Escape',
                'tab': 'Tab',
                'space': 'Space',
                'backspace': 'Backspace',
                'delete': 'Delete',
                'up': 'ArrowUp',
                'down': 'ArrowDown',
                'left': 'ArrowLeft',
                'right': 'ArrowRight',
            };
            
            const parts = keys.toLowerCase().split('+');
            const modifiers = [];
            let key = '';
            
            for (const part of parts) {
                if (keyMap[part]) {
                    modifiers.push(keyMap[part]);
                } else {
                    // Handle F-keys and single characters
                    if (part.match(/^f\d+$/)) {
                        key = part.toUpperCase();
                    } else {
                        key = part.length === 1 ? part : part.charAt(0).toUpperCase() + part.slice(1);
                    }
                }
            }
            
            const combo = [...modifiers, key].join('+');
            await page.keyboard.press(combo);
            
            output({ success: true, keys: combo });
        } catch (error) {
            logError('keyboard', error);
            output({ success: false, error: error.message });
        }
    },

    async type({ text }) {
        try {
            if (!page) throw new Error('No page open');
            await page.keyboard.type(text);
            output({ success: true, text });
        } catch (error) {
            logError('type', error);
            output({ success: false, error: error.message });
        }
    },

    async goto({ url }) {
        try {
            if (!page) throw new Error('No page open');
            await page.goto(url, { waitUntil: 'networkidle' });
            output({ success: true, url });
        } catch (error) {
            logError('goto', error);
            output({ success: false, error: error.message });
        }
    },

    async waitFor({ selector, timeout = 30000 }) {
        try {
            if (!page) throw new Error('No page open');
            await page.waitForSelector(selector, { timeout });
            output({ success: true, selector });
        } catch (error) {
            logError('waitFor', error);
            output({ success: false, error: error.message });
        }
    },

    async close() {
        try {
            aiAgent = null;
            if (browser) {
                await browser.close();
                browser = null;
                page = null;
            }
            output({ success: true });
        } catch (error) {
            logError('close', error);
            output({ success: false, error: error.message });
        }
    },
};

// Main loop - read commands from stdin
const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    terminal: false,
});

rl.on('line', async (line) => {
    try {
        const command = JSON.parse(line);
        const handler = handlers[command.action];
        
        if (!handler) {
            output({ success: false, error: `Unknown action: ${command.action}` });
            return;
        }
        
        await handler(command);
    } catch (error) {
        logError('command-handler', error);
        output({ success: false, error: error.message });
    }
});

// Handle process termination
process.on('SIGTERM', async () => {
    if (browser) await browser.close();
    process.exit(0);
});

process.on('SIGINT', async () => {
    if (browser) await browser.close();
    process.exit(0);
});

// Signal ready
output({ ready: true, version: '1.0.0' });
