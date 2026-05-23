# Steps for making a new deployment

## Create Oasis project (optional)
Create a new Oasis project (if there isn't any)
```
oasis rofl init
oasis rofl create --network testnet
```

## Build and the image
Run the following command
```
oasis rofl build
```

## Import environment variables
```
oasis rofl secret import .env.example
oasis rofl update
```
(Hint: if you changed sth manually in rofl.yaml, you can use ```oasis rofl update``` to make your change work)

## Deploy the image
```
oasis rofl deploy
```

## Show the deployment
After deployment you can check the status of deployment by using
```
oasis rofl machine show
```

It may take some time after the deployment because the applciation needs to start

## Top up the machine
After successfully testing, you can top up the machine so that it keeps your application longer (the default expiration time is very short), here is an example of top up the machine for 2 more hours
```
oasis rofl machine top-up --term hour --term-count 2
```

## Show the account (optional)
In case you may need to top up your oasis account by getting some TEST token from the faucet https://faucet.testnet.oasis.io/, do the following command to see your account address
```
oasis account show
```

## Common Errors:
1. Oasis update failed with error msg ```insufficient gas```, try to do ```oasis rofl update --gas-limit XXXXXX```
2. Deployment failed with error msg ```no space left```, manually change in ```rofl.yml``` the disk to sth like ```17000``` instead of using ```20000```
3. Deployment failed with error msg ```can not find the node```, manually delete the ```machines``` section in ```rofl.yml``` and redo ```oasis rofl update``` then ```oasis rofl deploy```
4. The deployment mahcine goes down after sometime, you need to top it up after the deployment ```oasis rofl machine top-up --term hour --term-count <hours>```