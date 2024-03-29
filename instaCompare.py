import json

followersRaw = open('followers_1.json')
followersJson = json.load(followersRaw)
followersArr = []

followingRaw = open('following.json')
followingJson = json.load(followingRaw)
followingArr = []

notFollowingMeBack = []
# print(followingJson)
for i in followersJson:
    followersArr.append(i['string_list_data'][0]['value'])

for i in followingJson['relationships_following']:
    followingArr.append(i['string_list_data'][0]['value'])

for i in followingArr:
    if i not in followersArr:
        notFollowingMeBack.append(i)

print(notFollowingMeBack)
