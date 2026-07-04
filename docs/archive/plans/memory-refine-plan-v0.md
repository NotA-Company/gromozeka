I want following in `internal/bot/common/handlers/user_data.py` handler:

1. Fix tools description so LLM need to add only some persistent memories, not something, that will be unrelevant tomorrow.

2. Add ability to refine memories about user in chat:
* have dome dict of chatId+ThreadId+UserId -> {newMessagesCount:int, lastProcessedTS: int, ...}
* On new messages increment counter of user's messages
* add cron job task, which will:

if user's now() - lastProcessedTS more than treshold OR newMessagesCount more that different treshold run memory refinement process:
Get last processed message data from user metadata (we need to use date instead of MessageID as for Max messageId isn't sequential) and if there are more messages that constant treshold (let's use 5 for now), then
run GenerateTextViaLLM with enabled tools: user memory manipulation + chat_search + current_date + something else usefull for it, with prompt from config + model from config (with fallback model support) and list unhandled messages with some cap (let's add constant for this cap. let's use 128 for now) + old user summarisation for memory refinement. prompt should say something like "use memory manipulation tools to add persistent knowledbe about user in chat + based on previous summarisation\bio + messages, answer with summarisation of short memory about user"

So in result we will update user's persistent knowledge + user temporary summary knowledge to add it to context later.
Ans save summary\bui\temporary-memory to user's metadata.

Also, as we currently add knowledbe about user to context, do the same with temporary memory, so bot will have better context memory about users in chat.